#!/usr/bin/env python3
"""Antigravity PreInvocation hook: inject live context alerts into the prompt.

Reads the active conversation's Antigravity SQLite DB (with transcript.jsonl fallback)
using Python standard library only and emits `injectSteps` JSON on stdout.
Uses stateless reverse scanning of transcript.jsonl to throttle repeated alerts.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

ALERT_PCT_RE = re.compile(r"\[(?:上下文预警|Context Alert)\s+(\d+(?:\.\d+)?)%\]")


def read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = 0
    for shift_idx in range(10):
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << (shift_idx * 7)
        if b < 0x80:
            return val, pos
    raise ValueError("varint overflow")


def iter_pb_fields(buf: bytes):
    pos = 0
    n = len(buf)
    while pos < n:
        tag, pos = read_varint(buf, pos)
        fn = tag >> 3
        wt = tag & 7
        if fn == 0:
            break
        if wt == 0:
            val, pos = read_varint(buf, pos)
        elif wt == 2:
            length, pos = read_varint(buf, pos)
            if length < 0 or pos + length > n:
                break
            val = buf[pos : pos + length]
            pos += length
        elif wt == 1:
            if pos + 8 > n:
                break
            val = buf[pos : pos + 8]
            pos += 8
        elif wt == 5:
            if pos + 4 > n:
                break
            val = buf[pos : pos + 4]
            pos += 4
        else:
            break
        yield fn, wt, val


def last_pb_field(buf: bytes, field_no: int, wire: int) -> Any | None:
    result = None
    for fn, wt, val in iter_pb_fields(buf):
        if fn == field_no and wt == wire:
            result = val
    return result


def parse_gen_blob(blob: bytes) -> tuple[int, int, int, int]:
    """Return (uncached_in, cached_in, window_used, max_context_tokens)."""
    chat = last_pb_field(blob, 1, 2)
    if not chat:
        return 0, 0, 0, 0

    uncached_in = 0
    cached_in = 0
    usage = last_pb_field(chat, 4, 2)
    if usage:
        u2 = last_pb_field(usage, 2, 0)
        u5 = last_pb_field(usage, 5, 0)
        uncached_in = int(u2 or 0)
        cached_in = int(u5 or 0)

    window_used = 0
    max_ctx = 0
    m9 = last_pb_field(chat, 9, 2)
    if m9:
        m10 = last_pb_field(m9, 10, 2)
        if m10:
            w1 = last_pb_field(m10, 1, 0)
            w4 = last_pb_field(m10, 4, 0)
            window_used = int(w1 or 0)
            max_ctx = int(w4 or 0)

    return uncached_in, cached_in, window_used, max_ctx


def resolve_memory_home() -> Path:
    override = os.environ.get("MILKFROG_MEMORY_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".gemini"


def _valid_cid(cid: str) -> bool:
    return bool(cid) and all(ch.isalnum() or ch in ("-", "_") for ch in cid)


def find_conversation_db(payload: dict[str, Any]) -> Path | None:
    cid = str(payload.get("conversationId") or "").strip()
    if not _valid_cid(cid):
        return None
    candidates: list[Path] = []
    tpath = str(payload.get("transcriptPath") or "").strip()
    if tpath:
        p = Path(tpath)
        for parent in p.parents:
            if parent.name in ("antigravity", "antigravity-ide", "antigravity-cli"):
                candidates.append(parent / "conversations" / f"{cid}.db")
                break
    mem_home = resolve_memory_home()
    for prod in ("antigravity", "antigravity-ide", "antigravity-cli"):
        candidates.append(mem_home / prod / "conversations" / f"{cid}.db")
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def resolve_transcript_path(payload: dict[str, Any], db_path: Path | None) -> Path | None:
    tpath = str(payload.get("transcriptPath") or "").strip()
    if tpath:
        p = Path(tpath)
        if p.is_file():
            return p
    cid = str(payload.get("conversationId") or "").strip()
    if db_path is not None and _valid_cid(cid):
        cand = db_path.parent.parent / "brain" / cid / ".system_generated" / "logs" / "transcript.jsonl"
        if cand.is_file():
            return cand
    return None


def read_db_context(db_path: Path) -> tuple[int, int, int, int]:
    """Return (used_tokens, uncached_in, cached_in, max_context_tokens)."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=0.5)
    try:
        rows = conn.execute(
            "SELECT idx, data FROM gen_metadata ORDER BY idx DESC LIMIT 20"
        ).fetchall()
    finally:
        conn.close()

    used = 0
    uncached = 0
    cached = 0
    max_ctx = 0
    for _, data in rows:
        if not data:
            continue
        try:
            u_in, c_in, w_used, lim = parse_gen_blob(bytes(data))
        except Exception:
            continue
        if max_ctx <= 0 and lim > 0:
            max_ctx = lim
        if used <= 0:
            api_in = u_in + c_in
            if api_in > 0:
                used = api_in
                uncached = u_in
                cached = c_in
            elif w_used > 0:
                used = w_used
        if used > 0 and max_ctx > 0:
            break
    return used, uncached, cached, max_ctx


def iter_transcript_lines_rev(path: Path, max_bytes: int = 8 * 1024 * 1024) -> Iterator[str]:
    """Yield non-empty lines from end of file without splitting UTF-8 characters."""
    size = path.stat().st_size
    if size <= 0:
        return
    pos = size
    stop_at = max(0, size - max_bytes)
    carry = b""
    chunk_size = 262_144
    with path.open("rb") as fh:
        while pos > stop_at:
            read_start = max(stop_at, pos - chunk_size)
            fh.seek(read_start)
            buf = fh.read(pos - read_start) + carry
            pos = read_start
            lines = buf.split(b"\n")
            if pos > 0:
                carry = lines[0]
                complete = lines[1:]
            else:
                carry = b""
                complete = lines
            for raw in reversed(complete):
                line = raw.strip()
                if line:
                    yield line.decode("utf-8", errors="replace")


def read_transcript_fallback(transcript_path: str) -> tuple[int, int, int]:
    """Tail-read transcript.jsonl for latest PLANNER_RESPONSE token counts."""
    p = Path(transcript_path)
    if not p.is_file():
        return 0, 0, 0
    for line in iter_transcript_lines_rev(p, max_bytes=512 * 1024):
        if '"PLANNER_RESPONSE"' not in line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "PLANNER_RESPONSE" and (
            "input_tokens" in obj or "cache_read_tokens" in obj
        ):
            u_in = int(obj.get("input_tokens") or 0)
            c_in = int(obj.get("cache_read_tokens") or 0)
            if u_in + c_in > 0:
                return u_in + c_in, u_in, c_in
    return 0, 0, 0


def read_recent_alert_state(
    transcript_path: Path | None, cooldown_calls: int
) -> tuple[int | None, float | None]:
    """Return (planner_calls_since_last_alert, last_alert_pct), stopping early."""
    if cooldown_calls <= 1 or transcript_path is None or not transcript_path.is_file():
        return None, None
    calls_since = 0
    for line in iter_transcript_lines_rev(transcript_path):
        is_planner = '"PLANNER_RESPONSE"' in line
        is_sdk_msg = '"SYSTEM_SDK"' in line and '"SYSTEM_MESSAGE"' in line
        if not is_planner and not is_sdk_msg:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        typ = obj.get("type")
        if typ == "PLANNER_RESPONSE":
            calls_since += 1
            if calls_since >= cooldown_calls:
                return calls_since, None
        elif typ == "SYSTEM_MESSAGE" and obj.get("source") == "SYSTEM_SDK":
            match = ALERT_PCT_RE.search(str(obj.get("content") or ""))
            if match:
                return calls_since, float(match.group(1))
    return None, None


def should_suppress_alert(
    pct: float | None,
    calls_since: int | None,
    last_alert_pct: float | None,
    settings: dict[str, Any],
) -> bool:
    """Throttle repeat alerts to once per cooldown_calls, with one critical bypass."""
    cooldown = int(settings["cooldown_calls"])
    if cooldown <= 1 or calls_since is None or calls_since >= cooldown:
        return False
    crit_pct = float(settings["critical_percent"])
    eff_crit = max(float(settings["warn_percent"]), crit_pct)
    if 0.0 < crit_pct <= 100.0 and pct is not None and pct >= eff_crit:
        if last_alert_pct is None or last_alert_pct < eff_crit:
            return False
    return True


def load_hook_settings() -> dict[str, Any]:
    cfg_path = Path(__file__).resolve().parent / "config.json"
    defaults: dict[str, Any] = {
        "enabled": True,
        "mode": "threshold",
        "warn_percent": 80,
        "cooldown_calls": 3,
        "critical_percent": 92,
        "lang": "zh",
    }
    if not cfg_path.is_file():
        return defaults
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    lang = cfg.get("lang")
    if lang in ("zh", "en"):
        defaults["lang"] = lang
    hook_cfg = cfg.get("context_hook")
    if isinstance(hook_cfg, dict):
        if "enabled" in hook_cfg:
            defaults["enabled"] = bool(hook_cfg["enabled"])
        if hook_cfg.get("mode") in ("always", "threshold"):
            defaults["mode"] = hook_cfg["mode"]
        wp = hook_cfg.get("warn_percent")
        if isinstance(wp, (int, float)) and not isinstance(wp, bool):
            defaults["warn_percent"] = float(wp)
        cd = hook_cfg.get("cooldown_calls")
        if isinstance(cd, (int, float)) and not isinstance(cd, bool):
            defaults["cooldown_calls"] = max(1, int(cd))
        cp = hook_cfg.get("critical_percent")
        if isinstance(cp, (int, float)) and not isinstance(cp, bool):
            defaults["critical_percent"] = 0.0 if cp <= 0 else min(100.0, float(cp))
    return defaults


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def build_message(
    used: int, limit: int, settings: dict[str, Any], *, throttled: bool = False
) -> str | None:
    if not settings["enabled"] or used <= 0:
        return None
    pct = (used / limit * 100.0) if limit > 0 else None
    warn_pct = float(settings["warn_percent"])
    is_high = pct is not None and pct >= warn_pct
    if settings["mode"] == "threshold":
        if not is_high or throttled:
            return None

    lang = settings["lang"]
    used_s = f"{fmt_tokens(used)} ({used:,})"
    if limit > 0 and pct is not None:
        limit_s = f"{fmt_tokens(limit)} ({limit:,})"
        pct_s = f"{pct:.1f}%"
    else:
        limit_s = "?"
        pct_s = "?%"

    if lang == "en":
        if is_high and not throttled:
            return (
                f"[Context Alert {pct_s}] Used {used_s} / {limit_s} tokens "
                f"(>= {warn_pct:g}% threshold). Before continuing or compacting, "
                "check whether any user-stated bans, corrections, key decisions, "
                "or reusable pitfalls from this session have not been saved to memory yet; "
                "if none, ignore this message."
            )
        return f"[Context] {fmt_tokens(used)} / {fmt_tokens(limit) if limit > 0 else '?'} ({pct_s})"

    if is_high and not throttled:
        return (
            f"[上下文预警 {pct_s}] 当前已用 {used_s} / {limit_s} tokens"
            f"（已达 {warn_pct:g}% 预警线）。为防自动或手动压缩丢失未落盘规则，"
            "请先自查本轮是否有用户提出的禁用项、纠偏、关键决定或实测踩坑尚未写入记忆/Skill，优先补写后再继续；如果没有请忽略本消息。"
        )
    return f"[上下文] {fmt_tokens(used)} / {fmt_tokens(limit) if limit > 0 else '?'} ({pct_s})"


def write_json_stdout(obj: dict[str, Any]) -> None:
    raw = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        write_json_stdout({})
        return 0

    try:
        settings = load_hook_settings()
        used = 0
        limit = 0
        db_path = find_conversation_db(payload)
        if db_path is not None:
            try:
                used, _, _, limit = read_db_context(db_path)
            except Exception:
                used = 0
        tpath = resolve_transcript_path(payload, db_path)
        if used <= 0 and tpath is not None:
            used, _, _ = read_transcript_fallback(str(tpath))

        pct = (used / limit * 100.0) if (used > 0 and limit > 0) else None
        throttled = False
        if settings["enabled"] and pct is not None and pct >= float(settings["warn_percent"]):
            calls_since, last_alert_pct = read_recent_alert_state(
                tpath, int(settings["cooldown_calls"])
            )
            throttled = should_suppress_alert(pct, calls_since, last_alert_pct, settings)

        msg = build_message(used, limit, settings, throttled=throttled)
        out: dict[str, Any] = {}
        if msg:
            # Omit metadata: Antigravity's proto scrubber panics on string-valued map entries.
            out = {
                "injectSteps": [
                    {
                        "systemMessage": {
                            "systemMessage": msg,
                        }
                    }
                ]
            }
        write_json_stdout(out)
    except Exception:
        write_json_stdout({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

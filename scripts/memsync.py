#!/usr/bin/env python3
"""memsync.py - Dual-layer memory operations and snapshot sync tool (stdlib only).

Usage:
  python3 memsync.py doctor [--json]
  python3 memsync.py bootstrap [--lang zh|en] [--agents-cache on|off] ...
  python3 memsync.py config show | set ...
  python3 memsync.py lint
  python3 memsync.py sync-plan
  python3 memsync.py global-input
  python3 memsync.py apply --scope <id> <draft.md> [--dry-run] [--no-copy]
  python3 memsync.py show <scope> <target> [--version current|before|both] [--stdout]
  python3 memsync.py search <query> [--scope all|<id>] [--max-matches N] [--regex] [--stdout]
  python3 memsync.py init <path> [--summary "..."] [--name <slug>] [--no-manage-agents]
  python3 memsync.py ws list | add | ignore | unignore | enable | disable | manage-agents
  python3 memsync.py hook install | status | uninstall
  python3 memsync.py copy-global [--targets a,b] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


def resolve_memory_home() -> Path:
    override = os.environ.get("MILKFROG_MEMORY_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".gemini").resolve()


MEMORY_HOME = resolve_memory_home()
OPS = MEMORY_HOME / "memory-ops"
WORK, LOGS, BACKUP = OPS / "work", OPS / "logs", OPS / "backup"
CONFIG_FILE = OPS / "config.json"
LEGACY_REGISTRY_FILE = OPS / "workspaces.json"
STATE_FILE = OPS / "sync-state.json"
STATUS_FILE = OPS / "status.json"
AGY_CONFIG = MEMORY_HOME / "config" / "config.json"
AGY_PROJECTS_DIR = MEMORY_HOME / "config" / "projects"
AGY_SIDECARS_DIR = MEMORY_HOME / "config" / "sidecars"
AGY_PLUGINS_DIR = MEMORY_HOME / "config" / "plugins"
CONTEXT_HOOK_PLUGIN_ID = "milkfrog-context-hook"
CONTEXT_HOOK_PLUGIN_DIR = AGY_PLUGINS_DIR / CONTEXT_HOOK_PLUGIN_ID

GLOBAL_ROOT = MEMORY_HOME
GLOBAL_GEMINI = GLOBAL_ROOT / "GEMINI.md"
GLOBAL_MEM = GLOBAL_ROOT / "memories"
GLOBAL_AGENTS = GLOBAL_ROOT / "AGENTS.md"

# Profile budgets:
# - standard: fits unmodified Antigravity IDE (24,000-byte per-file rule cap, 20K rules token budget)
# - extended: for users who expanded IDE rule/context limits
BUDGET_PROFILES: dict[str, dict[str, Any]] = {
    "standard": {
        "global": {
            "gemini_warn": 16_000, "gemini_hard": 24_000,
            "head_warn": 6_000, "head_hard": 12_000,
            "agents_warn": 16_000, "agents_hard": 24_000,
        },
        "project": {
            "gemini_warn": 16_000, "gemini_hard": 24_000,
            "head_warn": 3_000, "head_hard": 8_000,
            "agents_warn": 16_000, "agents_hard": 24_000,
        },
        "rules_total_warn": 36_000,
        "rules_total_hard": 48_000,
    },
    "extended": {
        "global": {
            "gemini_warn": 40_000, "gemini_hard": 160_000,
            "head_warn": 16_000, "head_hard": 64_000,
            "agents_warn": 32_000, "agents_hard": 128_000,
        },
        "project": {
            "gemini_warn": 24_000, "gemini_hard": 96_000,
            "head_warn": 4_000, "head_hard": 16_000,
            "agents_warn": 24_000, "agents_hard": 96_000,
        },
        "rules_total_warn": 120_000,
        "rules_total_hard": 480_000,
    },
}

LINE_WARN = 220
STALE_PROJECT_DAYS = 60
BACKUP_KEEP = 14
DIFF_CONTEXT_LINES = 4
SMALL_MOD_FULLTEXT_BYTES = 4_096
INLINE_DIFF_MIN_LINE_CHARS = 120
SHRINK_WARN_RATIO = 0.70
SHRINK_WARN_MIN_BYTES = 2_000
WORK_KEEP_DAYS = 14

REQUIRED_FM = ["name", "description", "type", "scope", "updated"]
TYPES = {"user", "feedback", "project", "reference"}
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKID[A-Za-z0-9]{12,}|AIza[0-9A-Za-z\-_]{30,}"
    r"|(?i:password|passwd|secret|api[_-]?key)\s*[:=]\s*[A-Za-z0-9_\-]{8,})"
)

GLOBAL_INDEX_HEADINGS = ("## 全局索引", "## Global Index")
GLOBAL_WS_HEADINGS = ("## 已注册工作区", "## Registered Workspaces")
PROJECT_INDEX_HEADINGS = ("## 项目索引", "## Project Index")

I18N: dict[str, dict[str, str]] = {
    "zh": {
        "global_ws_heading": "## 已注册工作区",
        "global_index_heading": "## 全局索引",
        "project_index_heading": "## 项目索引",
        "global_summary": "全局跨工作区记忆、偏好、规范与参考索引",
        "ignored_label": "暂不纳管（临时/忽略目录）",
        "default_ws_summary": "{name} 独立工作区",
        "default_ignore_reason": "临时目录",
    },
    "en": {
        "global_ws_heading": "## Registered Workspaces",
        "global_index_heading": "## Global Index",
        "project_index_heading": "## Project Index",
        "global_summary": "Global cross-workspace memory, preferences, conventions, and references",
        "ignored_label": "Ignored (temporary/unmanaged directories)",
        "default_ws_summary": "{name} standalone workspace",
        "default_ignore_reason": "temporary directory",
    },
}


def today_date() -> dt.date:
    return dt.date.today()


def nbytes(s: str) -> int:
    return len(s.encode("utf-8"))


def read_text(p: Path) -> str:
    return Path(p).read_text(encoding="utf-8-sig")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes()) if Path(p).exists() else ""


def norm_path(p: str | Path) -> str:
    resolved = str(Path(p).expanduser().resolve())
    trimmed = resolved.rstrip("\\/") or resolved
    return os.path.normcase(trimmed)


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def is_nested_path(p_a: str | Path, p_b: str | Path) -> bool:
    a = Path(os.path.normcase(str(Path(p_a).expanduser().resolve())))
    b = Path(os.path.normcase(str(Path(p_b).expanduser().resolve())))
    if a == b:
        return False
    return _is_relative_to(a, b) or _is_relative_to(b, a)


def is_child_path(child: str | Path, parent: str | Path) -> bool:
    c = Path(os.path.normcase(str(Path(child).expanduser().resolve())))
    p = Path(os.path.normcase(str(Path(parent).expanduser().resolve())))
    return c != p and _is_relative_to(c, p)


def write_utf8_nobom(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    cleaned = content.replace("\r\n", "\n").rstrip("\n") + "\n"
    p.write_bytes(cleaned.encode("utf-8"))


def backup_file(p: Path, tag: str) -> Path | None:
    if not p.exists() or p.stat().st_size == 0:
        return None
    BACKUP.mkdir(parents=True, exist_ok=True)
    bk = BACKUP / f"{tag}-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    shutil.copy2(p, bk)
    for old in sorted(BACKUP.glob(f"{tag}-*.md"))[:-BACKUP_KEEP]:
        old.unlink()
    return bk


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def fence_block(content: str, lang: str = "") -> str:
    runs = re.findall(r"`+", content or "")
    ticks = "`" * max(4, max((len(x) for x in runs), default=0) + 1)
    body = (content or "").strip()
    return f"{ticks}{lang}\n{body}\n{ticks}"


def prune_work_files(keep_days: int = WORK_KEEP_DAYS) -> int:
    if not WORK.exists() or keep_days <= 0:
        return 0
    cutoff = today_date() - dt.timedelta(days=keep_days)
    removed = 0
    for f in WORK.glob("*.md"):
        m = re.search(r"-(\d{4}-\d{2}-\d{2})\.md$", f.name)
        if not m:
            continue
        fdate = parse_date(m.group(1))
        if fdate and fdate < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        log("prune-work", f"removed={removed} keep_days={keep_days}")
    return removed


def _nearest_heading(lines: list[str], line_idx: int) -> str:
    idx = min(max(line_idx, 0), len(lines) - 1) if lines else -1
    while idx >= 0:
        ln = lines[idx].strip()
        if re.match(r"^#{1,4}\s+\S", ln):
            return ln
        idx -= 1
    return ""


def build_contextual_diff(
    old_text: str,
    new_text: str,
    label: str,
    context: int = DIFF_CONTEXT_LINES,
) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    raw = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"before/{label}",
        tofile=f"after/{label}",
        lineterm="",
        n=context,
    ))
    enriched: list[str] = []
    for ln in raw:
        m = re.match(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@$", ln)
        if m:
            new_ln = max(int(m.group(2)) - 1, 0)
            old_ln = max(int(m.group(1)) - 1, 0)
            heading = _nearest_heading(new_lines, new_ln) or _nearest_heading(old_lines, old_ln)
            if heading:
                enriched.append(f"{ln} [section: {heading}]")
                continue
        enriched.append(ln)
    return "\n".join(enriched)


_INLINE_TOK_RE = re.compile(
    r"`[^`]+`|[A-Za-z0-9_./:@+-]+|[\u4e00-\u9fff]+|[^\s`A-Za-z0-9_\u4e00-\u9fff]+|`|\s+"
)
_INLINE_TRIM_CHARS = " \t、，,;；：:。！？（）()【】[]「」『』《》<>|｜/\\-—"


def _clean_inline_piece(piece: str) -> str:
    s = piece.strip(_INLINE_TRIM_CHARS)
    if not s:
        return ""
    if len(s) > 80:
        s = s[:77] + "..."
    return s


def extract_inline_deltas(
    old_text: str,
    new_text: str,
    min_chars: int = INLINE_DIFF_MIN_LINE_CHARS,
) -> list[str]:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    notes: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for off in range(i2 - i1):
            oln, nln = old_lines[i1 + off], new_lines[j1 + off]
            if max(len(oln), len(nln)) < min_chars:
                continue
            otoks = _INLINE_TOK_RE.findall(oln)
            ntoks = _INLINE_TOK_RE.findall(nln)
            tsm = difflib.SequenceMatcher(None, otoks, ntoks, autojunk=False)
            if tsm.ratio() < 0.45:
                continue
            rems: list[str] = []
            adds: list[str] = []
            for ttag, a1, a2, b1, b2 in tsm.get_opcodes():
                if ttag in ("delete", "replace"):
                    p = _clean_inline_piece("".join(otoks[a1:a2]))
                    if p and p not in rems:
                        rems.append(p)
                if ttag in ("insert", "replace"):
                    p = _clean_inline_piece("".join(ntoks[b1:b2]))
                    if p and p not in adds:
                        adds.append(p)
            common = set(rems) & set(adds)
            if common:
                rems = [x for x in rems if x not in common]
                adds = [x for x in adds if x not in common]
            if not rems and not adds:
                continue
            lineno = j1 + off + 1
            rem_s = " / ".join(rems[:4]) + (" ..." if len(rems) > 4 else "")
            add_s = " / ".join(adds[:4]) + (" ..." if len(adds) > 4 else "")
            if rems and adds:
                notes.append(
                    f"- L{lineno} inline delta (co-occurring delete+add does NOT imply replacement): "
                    f"removed [{rem_s}] | added [{add_s}]"
                )
            elif rems:
                notes.append(f"- L{lineno} inline removed: [{rem_s}]")
            else:
                notes.append(f"- L{lineno} inline added: [{add_s}]")
            if len(notes) >= 8:
                return notes
    return notes


def log(cmd: str, msg: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "sync.log", "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {cmd} {msg}\n")


class Report:
    def __init__(self, title: str):
        self.lines = [f"# {title} · {dt.datetime.now():%Y-%m-%d %H:%M}"]
        self.err = 0
        self.warn = 0

    def h(self, title: str) -> None:
        self.lines += ["", f"## {title}"]

    def i(self, msg: str) -> None:
        self.lines.append(f"- INFO {msg}")

    def w(self, msg: str) -> None:
        self.warn += 1
        self.lines.append(f"- WARN {msg}")

    def e(self, msg: str) -> None:
        self.err += 1
        self.lines.append(f"- ERROR {msg}")

    def raw(self, msg: str) -> None:
        self.lines.append(msg)

    def save(self, kind: str) -> int:
        WORK.mkdir(parents=True, exist_ok=True)
        out = WORK / f"{kind}-{today_date()}.md"
        self.lines.insert(1, f"\nSummary: ERROR {self.err} / WARN {self.warn}")
        write_utf8_nobom(out, "\n".join(self.lines))
        log(kind, f"errors={self.err} warns={self.warn}")
        print(f"{kind}: errors={self.err} warns={self.warn} report={out}")
        return 1 if self.err else 0


def default_config() -> dict[str, Any]:
    return {
        "version": 2,
        "lang": "zh",
        "mode": {
            "agents_cache_enabled": True,
            "schedule_enabled": False,
            "auto_discover_unregistered": True,
        },
        "schedule": {
            "time": "06:00",
            "timezone": guess_local_timezone(),
            "sidecar_id": "daily-agents-memory-sync",
        },
        "limits": {
            "profile": "standard",
        },
        "cross_tool_sync": {
            "enabled": False,
            "auto_copy_on_global_apply": True,
            "targets": {},
        },
        "context_hook": {
            "enabled": False,
            "mode": "threshold",
            "warn_percent": 80,
            "cooldown_calls": 3,
            "critical_percent": 92,
        },
        "workspaces": [],
        "ignored": [],
    }


def guess_local_timezone() -> str:
    try:
        tz = dt.datetime.now().astimezone().tzinfo
        key = getattr(tz, "key", None)
        if isinstance(key, str) and "/" in key:
            return key
    except Exception:
        pass
    offset = dt.datetime.now().astimezone().utcoffset()
    if offset == dt.timedelta(hours=8):
        return "Asia/Shanghai"
    return "UTC"


def _normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = default_config()
    if not isinstance(raw, dict):
        return cfg

    # Upgrade legacy workspaces.json keys smoothly if present
    cfg["lang"] = raw.get("lang") if raw.get("lang") in I18N else cfg["lang"]

    raw_mode = raw.get("mode") if isinstance(raw.get("mode"), dict) else {}
    for k in ("agents_cache_enabled", "schedule_enabled", "auto_discover_unregistered"):
        if k in raw_mode:
            cfg["mode"][k] = bool(raw_mode[k])

    raw_sched = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    for k in ("time", "timezone", "sidecar_id"):
        if raw_sched.get(k):
            cfg["schedule"][k] = str(raw_sched[k])

    raw_lim = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
    if raw_lim.get("profile") in BUDGET_PROFILES:
        cfg["limits"]["profile"] = raw_lim["profile"]
    if isinstance(raw_lim.get("custom"), dict):
        cfg["limits"]["custom"] = raw_lim["custom"]

    if isinstance(raw.get("cross_tool_sync"), dict):
        cts = raw["cross_tool_sync"]
        cfg["cross_tool_sync"]["enabled"] = bool(cts.get("enabled", bool(cts.get("targets"))))
        cfg["cross_tool_sync"]["auto_copy_on_global_apply"] = bool(cts.get("auto_copy_on_global_apply", True))
        if isinstance(cts.get("targets"), dict):
            cfg["cross_tool_sync"]["targets"] = dict(cts["targets"])
    else:
        legacy_targets = raw.get("copy_targets")
        if isinstance(legacy_targets, dict) and legacy_targets:
            cfg["cross_tool_sync"]["targets"] = dict(legacy_targets)
            cfg["cross_tool_sync"]["enabled"] = True
        if "auto_copy_on_global_apply" in raw:
            cfg["cross_tool_sync"]["auto_copy_on_global_apply"] = bool(raw["auto_copy_on_global_apply"])

    raw_hook = raw.get("context_hook") if isinstance(raw.get("context_hook"), dict) else {}
    if "enabled" in raw_hook:
        cfg["context_hook"]["enabled"] = bool(raw_hook["enabled"])
    if raw_hook.get("mode") in ("always", "threshold"):
        cfg["context_hook"]["mode"] = raw_hook["mode"]
    wp = raw_hook.get("warn_percent")
    if isinstance(wp, (int, float)) and not isinstance(wp, bool):
        cfg["context_hook"]["warn_percent"] = _clamp_warn_percent(wp)
    cd = raw_hook.get("cooldown_calls")
    if isinstance(cd, (int, float)) and not isinstance(cd, bool):
        cfg["context_hook"]["cooldown_calls"] = _clamp_cooldown(cd)
    cp = raw_hook.get("critical_percent")
    if isinstance(cp, (int, float)) and not isinstance(cp, bool):
        cfg["context_hook"]["critical_percent"] = _clamp_critical_percent(cp)

    if isinstance(raw.get("workspaces"), list):
        cfg["workspaces"] = list(raw["workspaces"])
    if isinstance(raw.get("ignored"), list):
        cfg["ignored"] = list(raw["ignored"])
    return cfg


def load_config() -> dict[str, Any]:
    if CONFIG_FILE.exists():
        return _normalize_config(json.loads(read_text(CONFIG_FILE)))
    if LEGACY_REGISTRY_FILE.exists():
        return _normalize_config(json.loads(read_text(LEGACY_REGISTRY_FILE)))
    return default_config()


def save_config(cfg: dict[str, Any]) -> None:
    write_utf8_nobom(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=2))


def get_budgets(cfg: dict[str, Any]) -> dict[str, Any]:
    profile = cfg.get("limits", {}).get("profile", "standard")
    base = json.loads(json.dumps(BUDGET_PROFILES.get(profile, BUDGET_PROFILES["standard"])))
    custom = cfg.get("limits", {}).get("custom")
    if isinstance(custom, dict):
        for scope_key in ("global", "project"):
            if isinstance(custom.get(scope_key), dict):
                base[scope_key].update(custom[scope_key])
        for top_key in ("rules_total_warn", "rules_total_hard"):
            if isinstance(custom.get(top_key), int):
                base[top_key] = custom[top_key]
    return base


def _check_budget(
    r: Report,
    label: str,
    actual: int,
    warn_lim: int,
    hard_lim: int,
    warn_hint: str = "consider trimming to keep rules focused",
) -> None:
    r.i(f"{label} {actual:,}/{warn_lim:,} bytes (hard cap {hard_lim:,})")
    if actual > hard_lim:
        r.e(f"{label} exceeded hard cap: {actual:,}>{hard_lim:,}")
    elif actual > warn_lim:
        r.w(f"{label} exceeded warn threshold: {actual:,}>{warn_lim:,} ({warn_hint})")


def parse_fm(text: str) -> tuple[dict[str, str] | None, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            fm: dict[str, str] = {}
            for ln in lines[1:idx]:
                m = re.match(r"^\s*([A-Za-z_]+):\s*(.*?)\s*$", ln)
                if m and m.group(2):
                    fm[m.group(1)] = m.group(2).strip().strip("\"'")
            return fm, "\n".join(lines[idx + 1:])
    return None, text


def parse_date(s: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat((s or "").strip()[:10])
    except ValueError:
        return None


def split_sections(text: str, titles: tuple[str, ...] | list[str]) -> dict[str, str]:
    out: dict[str, list[str]] = {"head": []}
    cur = "head"
    title_set = set(titles)
    for ln in text.splitlines():
        if ln.strip() in title_set:
            cur = ln.strip()
            out[cur] = []
            continue
        out[cur].append(ln)
    return {k: "\n".join(v) for k, v in out.items()}


def bullet_lines(s: str) -> list[str]:
    return [ln for ln in s.splitlines() if ln.startswith("- ")]


def ignored_norms(cfg: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in cfg.get("ignored", []):
        raw = item.get("path", "") if isinstance(item, dict) else str(item)
        if raw:
            out[norm_path(raw)] = raw
    return out


def is_memsync_agents(text: str) -> bool:
    low = text.lower()
    markers = ("memsync", "定时记忆同步", "memory-ops", "auto-generated snapshot")
    return any(m in low for m in markers) and "GEMINI.md" in text


def is_memsync_gemini(text: str) -> bool:
    return any(h in text for h in GLOBAL_INDEX_HEADINGS) or any(h in text for h in PROJECT_INDEX_HEADINGS)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"version": 1, "last_sync": "", "scopes": {}}
    return json.loads(read_text(STATE_FILE))


def save_state(st: dict[str, Any]) -> None:
    write_utf8_nobom(STATE_FILE, json.dumps(st, ensure_ascii=False, indent=2))


def make_scopes(cfg: dict[str, Any], only_enabled: bool = True) -> list[dict[str, Any]]:
    lang = cfg.get("lang", "zh")
    tr = I18N.get(lang, I18N["zh"])
    budgets = get_budgets(cfg)
    agents_on = bool(cfg.get("mode", {}).get("agents_cache_enabled", True))

    scopes: list[dict[str, Any]] = [{
        "id": "global",
        "kind": "global",
        "name": "global",
        "root": GLOBAL_ROOT,
        "gemini": GLOBAL_GEMINI,
        "mem_dir": GLOBAL_MEM,
        "agents": GLOBAL_AGENTS,
        "limits": budgets["global"],
        "index_headings": GLOBAL_INDEX_HEADINGS,
        "preferred_index_heading": tr["global_index_heading"],
        "summary": tr["global_summary"],
        "manage_agents": agents_on,
    }]
    for ws in cfg.get("workspaces", []):
        if only_enabled and not ws.get("enabled", True):
            continue
        root = Path(ws["path"]).expanduser()
        ws_manage = agents_on and bool(ws.get("manage_agents", True))
        scopes.append({
            "id": ws["name"],
            "kind": "project",
            "name": ws["name"],
            "root": root,
            "gemini": root / "GEMINI.md",
            "mem_dir": root / ".gemini" / "memories",
            "agents": root / "AGENTS.md",
            "limits": budgets["project"],
            "index_headings": PROJECT_INDEX_HEADINGS,
            "preferred_index_heading": tr["project_index_heading"],
            "summary": ws.get("summary", ""),
            "manage_agents": ws_manage,
            "raw_manage_agents": bool(ws.get("manage_agents", True)),
        })
    return scopes


def find_scope(cfg: dict[str, Any], scope_id: str) -> dict[str, Any] | None:
    for sc in make_scopes(cfg, only_enabled=False):
        if sc["id"] == scope_id:
            return sc
    return None


def workspace_global_fingerprint(sc: dict[str, Any]) -> str:
    if sc.get("manage_agents", True):
        return sha256_file(sc["agents"])
    parts = [f"gemini:{sha256_file(sc['gemini'])}"]
    if sc["mem_dir"].exists():
        for mf in sorted(sc["mem_dir"].glob("*.md")):
            parts.append(f"mem:{mf.name}:{sha256_file(mf)}")
    return sha256_bytes("\n".join(parts).encode("utf-8"))


def discover_agy_folder_workspaces() -> list[tuple[str, str]]:
    """Scan Antigravity IDE projects while skipping sidecar/cron/swarm virtual folders."""
    sidecar_ids: set[str] = set()
    if AGY_CONFIG.exists():
        try:
            cfg = json.loads(read_text(AGY_CONFIG))
            for sc in cfg.get("sidecars", {}).values():
                if isinstance(sc, dict) and sc.get("projectId"):
                    sidecar_ids.add(sc["projectId"])
        except Exception:
            pass

    found: dict[str, str] = {}
    if AGY_PROJECTS_DIR.exists():
        for jf in sorted(AGY_PROJECTS_DIR.glob("*.json")):
            try:
                data = json.loads(read_text(jf))
                pid = data.get("id") or jf.stem
                if pid in sidecar_ids or data.get("sidecar"):
                    continue
                for res in data.get("projectResources", {}).get("resources", []):
                    if not isinstance(res, dict):
                        continue
                    uri = res.get("folderUri") or (res.get("gitFolder") or {}).get("folderUri") or ""
                    if not uri.startswith("file:///"):
                        continue
                    raw = unquote(urlparse(uri).path)
                    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
                        raw = raw[1:]
                    if ".gemini/antigravity/swarm" in raw.lower():
                        continue
                    p = Path(raw)
                    if p.is_dir():
                        found[norm_path(p)] = str(p.resolve())
            except Exception:
                pass
    return [(k, found[k]) for k in sorted(found)]


def detect_external_targets() -> dict[str, str]:
    home = Path.home()
    candidates = {
        "codex": home / ".codex" / "AGENTS.md",
        "claude": home / ".claude" / "CLAUDE.md",
    }
    found: dict[str, str] = {}
    for name, target in candidates.items():
        if target.parent.exists():
            found[name] = str(target)
    return found


def detect_common_toolchains() -> dict[str, dict[str, str]]:
    """Read-only probe of common developer CLIs on PATH without touching private folders."""
    probes: list[tuple[str, list[str]]] = [
        ("python3", ["--version"]),
        ("python", ["--version"]),
        ("uv", ["--version"]),
        ("git", ["--version"]),
        ("node", ["--version"]),
        ("pnpm", ["--version"]),
        ("npm", ["--version"]),
        ("java", ["-version"]),
        ("mvn", ["--version"]),
        ("cargo", ["--version"]),
        ("go", ["version"]),
        ("docker", ["--version"]),
    ]
    found: dict[str, dict[str, str]] = {}
    for exe, args in probes:
        exe_path = shutil.which(exe)
        if not exe_path:
            continue
        ver = ""
        try:
            proc = subprocess.run(
                [exe_path, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2,
                check=False,
            )
            combined = (proc.stdout or proc.stderr or "").strip()
            if proc.returncode == 0 and combined:
                ver = combined.splitlines()[0].strip()[:120]
        except Exception:
            ver = ""
        if exe == "python3" and not ver and platform.system() == "Windows":
            continue  # skip Windows Store python3.exe alias stub
        found[exe] = {"path": exe_path, "version": ver or "(detected on PATH)"}
    return found


def inspect_file_status(path: Path, kind: str) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "bytes": 0, "memsync": False}
    txt = read_text(path)
    managed = is_memsync_gemini(txt) if kind == "gemini" else is_memsync_agents(txt)
    return {"exists": True, "bytes": nbytes(txt), "memsync": managed}


# ------------------------------------------------------------------ doctor
def cmd_doctor(args) -> int:
    cfg = load_config()
    cwd = Path.cwd().resolve()
    info = {
        "python": platform.python_version(),
        "os": platform.system(),
        "timezone": guess_local_timezone(),
        "memory_home": str(MEMORY_HOME),
        "ops_dir": str(OPS),
        "config_exists": CONFIG_FILE.exists(),
        "legacy_registry_exists": LEGACY_REGISTRY_FILE.exists(),
        "cwd": str(cwd),
        "global_files": {
            "GEMINI.md": inspect_file_status(GLOBAL_GEMINI, "gemini"),
            "AGENTS.md": inspect_file_status(GLOBAL_AGENTS, "agents"),
            "local-installed-tools.md": {"exists": (GLOBAL_MEM / "local-installed-tools.md").exists()},
        },
        "cwd_files": {
            "GEMINI.md": inspect_file_status(cwd / "GEMINI.md", "gemini"),
            "AGENTS.md": inspect_file_status(cwd / "AGENTS.md", "agents"),
            "is_git": (cwd / ".git").exists(),
        },
        "detected_cross_targets": detect_external_targets(),
        "detected_toolchains": detect_common_toolchains(),
        "discovered_agy_workspaces": [raw for _, raw in discover_agy_folder_workspaces()],
        "schedule_sidecar_exists": (AGY_SIDECARS_DIR / cfg["schedule"]["sidecar_id"] / "sidecar.json").exists(),
        "context_hook_installed": (CONTEXT_HOOK_PLUGIN_DIR / "hooks.json").exists(),
        "context_hook_script_exists": (OPS / "context_hook.py").exists(),
        "active_mode": cfg["mode"],
        "active_limits_profile": cfg["limits"]["profile"],
    }
    if getattr(args, "json", False):
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"python={info['python']} os={info['os']} tz={info['timezone']} home={info['memory_home']}")
        print(f"config_exists={info['config_exists']} legacy_exists={info['legacy_registry_exists']} profile={info['active_limits_profile']}")
        print(f"mode={json.dumps(info['active_mode'])}")
        print(f"global_files={json.dumps(info['global_files'])}")
        print(f"cwd_files={json.dumps(info['cwd_files'])}")
        print(f"detected_cross_targets={json.dumps(info['detected_cross_targets'])}")
        print(f"detected_toolchains={','.join(info['detected_toolchains'].keys()) or 'none'}")
        print(f"discovered_agy_workspaces={len(info['discovered_agy_workspaces'])}")
    return 0


# ------------------------------------------------------------------ lint
def _check_memory_entry(f: Path, sc: dict[str, Any], linked: set[Path], r: Report) -> None:
    if f.name.upper() in ("GEMINI.MD", "AGENTS.MD"):
        r.e(f"forbidden memory entry filename: {f.name}")
    if f.resolve() not in linked:
        r.e(f"orphan memory file (not listed in index): {f.name}")
    fm, body = parse_fm(read_text(f))
    if fm is None:
        r.e(f"{f.name} missing YAML frontmatter")
        return
    miss = [k for k in REQUIRED_FM if k not in fm]
    if miss:
        r.e(f"{f.name} missing frontmatter field(s): {','.join(miss)}")
    if fm.get("name") and fm["name"] != f.stem:
        r.e(f"{f.name} name='{fm['name']}' mismatches filename stem")
    if fm.get("type") and fm["type"] not in TYPES:
        r.e(f"{f.name} invalid type='{fm['type']}'")
    if fm.get("scope") and fm["scope"] != sc["kind"]:
        r.e(f"{f.name} scope='{fm['scope']}' mismatches directory scope '{sc['kind']}'")
    desc = fm.get("description", "")
    if not re.match(r"^[【\[]\d{4}-\d{2}-\d{2}", desc):
        r.w(f"{f.name} description lacks [YYYY-MM-DD ...] or 【YYYY-MM-DD ...】 date tag")
    up = parse_date(fm.get("updated"))
    if "updated" in fm and not up:
        r.e(f"{f.name} invalid updated date: {fm.get('updated')}")
    if fm.get("type") == "project" and up and (today_date() - up).days > STALE_PROJECT_DAYS:
        r.w(f"{f.name} project entry unchanged for >{STALE_PROJECT_DAYS} days; verify if archived")
    if SECRET_RE.search(body) and fm.get("sync") != "never":
        r.w(f"{f.name} looks like it contains credential patterns without sync: never")


def lint_scope(sc: dict[str, Any], cfg: dict[str, Any], r: Report) -> int:
    r.h(f"Scope [{sc['id']}] · {sc['root']}")
    g = sc["gemini"]
    total_rule_bytes = 0
    agents_cache_on = bool(cfg.get("mode", {}).get("agents_cache_enabled", True))

    if not g.exists():
        r.e(f"missing GEMINI.md: {g}")
    else:
        g_text = read_text(g)
        gb = nbytes(g_text)
        total_rule_bytes += gb
        lim = sc["limits"]
        _check_budget(r, "GEMINI.md bytes", gb, lim["gemini_warn"], lim["gemini_hard"])

        secs = split_sections(g_text, sc["index_headings"])
        hb = nbytes(secs["head"])
        _check_budget(r, "GEMINI.md header bytes", hb, lim["head_warn"], lim["head_hard"])

        matched_heading = next((h for h in sc["index_headings"] if h in secs), None)
        if not matched_heading:
            r.e(f"missing index section heading ({' / '.join(sc['index_headings'])})")
        else:
            idx = bullet_lines(secs[matched_heading])
            r.i(f"index entries: {len(idx)}")
            linked: set[Path] = set()
            for ln in idx:
                tag = ln[:48]
                if len(ln) > LINE_WARN:
                    r.w(f"index line >{LINE_WARN} chars ({len(ln)}): {tag}...")
                if not re.match(r"^- [【\[]\d{4}-\d{2}-\d{2} ", ln):
                    r.w(f"index line lacks [YYYY-MM-DD ...] prefix: {tag}...")
                m = re.search(r"\]\(([^)]+?\.md)\)", ln)
                if not m:
                    r.e(f"index line missing .md link: {tag}...")
                    continue
                target = (g.parent / m.group(1)).resolve()
                if not target.exists():
                    r.e(f"dangling index link (missing file): {m.group(1)}")
                linked.add(target)

            mem_files = sorted(sc["mem_dir"].glob("*.md")) if sc["mem_dir"].exists() else []
            r.i(f"memory entries: {len(mem_files)}")
            for f in mem_files:
                _check_memory_entry(f, sc, linked, r)

    ag = sc["agents"]
    if not agents_cache_on:
        if ag.exists():
            ab = nbytes(read_text(ag))
            r.i(f"index-only mode active (agents_cache_enabled=false); existing {ag.name} untouched ({ab:,} bytes)")
        else:
            r.i("index-only mode active (agents_cache_enabled=false); AGENTS.md not required")
    elif sc["kind"] == "project" and not sc.get("raw_manage_agents", True):
        if ag.exists():
            ag_text = read_text(ag)
            ab = nbytes(ag_text)
            total_rule_bytes += ab
            r.i(f"AGENTS.md unmanaged (manage_agents=false); kept original ({ab:,} bytes)")
            if SECRET_RE.search(ag_text):
                r.e("AGENTS.md matched secret pattern")
        else:
            r.i("AGENTS.md unmanaged (manage_agents=false); not created")
    elif not ag.exists():
        r.w(f"AGENTS.md snapshot not generated yet: {ag} (run sync-plan + apply)")
    else:
        ag_text = read_text(ag)
        ab = nbytes(ag_text)
        total_rule_bytes += ab
        hint = "keep <= 32KB if syncing to Codex" if sc["kind"] == "global" else "consider trimming to stay focused"
        _check_budget(r, "AGENTS.md bytes", ab, sc["limits"]["agents_warn"], sc["limits"]["agents_hard"], warn_hint=hint)
        if "GEMINI.md" not in ag_text:
            if sc["kind"] == "project" and not is_memsync_agents(ag_text):
                r.w(f"AGENTS.md is a foreign file without GEMINI.md pointer (migrate then apply, or ws manage-agents {sc['id']} --off)")
            else:
                r.w("AGENTS.md lacks pointer to GEMINI.md")
        if SECRET_RE.search(ag_text):
            r.e("AGENTS.md matched secret pattern")

    if sc["kind"] == "project" and (sc["root"] / ".git").exists():
        gi = sc["root"] / ".gitignore"
        if not gi.exists() or ".gemini/memories" not in read_text(gi):
            r.e(f"{sc['root']} is a git repo but .gitignore does not ignore .gemini/memories")

    return total_rule_bytes


def cmd_lint(_) -> int:
    cfg = load_config()
    budgets = get_budgets(cfg)
    scopes = make_scopes(cfg, only_enabled=True)
    r = Report("Memory System Lint (Scoped)")

    per_scope: dict[str, int] = {}
    for sc in scopes:
        per_scope[sc["id"]] = lint_scope(sc, cfg, r)

    g_bytes = per_scope.get("global", 0)
    r.h("Budgets & Workspace Registration")
    for sc in scopes:
        if sc["kind"] == "project":
            pair = g_bytes + per_scope[sc["id"]]
            _check_budget(
                r,
                f"global + {sc['id']} combined active rules",
                pair,
                budgets["rules_total_warn"],
                budgets["rules_total_hard"],
            )

    reg_norms = {norm_path(ws["path"]) for ws in cfg.get("workspaces", [])}
    ign_norms = set(ignored_norms(cfg).keys())
    for ws in cfg.get("workspaces", []):
        if ws.get("enabled", True) and not Path(ws["path"]).expanduser().is_dir():
            r.w(f"enabled workspace directory missing: {ws['name']} ({ws['path']})")

    if cfg.get("mode", {}).get("auto_discover_unregistered", True):
        for norm_p, raw_p in discover_agy_folder_workspaces():
            if norm_p in reg_norms or norm_p in ign_norms:
                continue
            if any(is_child_path(norm_p, ws["path"]) for ws in cfg.get("workspaces", [])):
                continue
            r.w(f"uninitialized Antigravity workspace detected: {raw_p}")

    if GLOBAL_GEMINI.exists():
        g_txt = read_text(GLOBAL_GEMINI)
        for ws in cfg.get("workspaces", []):
            if ws.get("enabled", True) and ws["name"] not in g_txt:
                r.w(f"global GEMINI.md registered workspaces section missing: {ws['name']}")

    return r.save("lint")


# --------------------------------------------------------------- diff/sync
def scan_memories_diff(sc: dict[str, Any], prev_scope_state: dict[str, Any]) -> dict[str, Any]:
    mem_dir = sc["mem_dir"]
    cur_files = {f.name: f for f in (sorted(mem_dir.glob("*.md")) if mem_dir.exists() else [])}
    prev_mems = prev_scope_state.get("memories", {})

    new_items, mod_items, del_items = [], [], []
    cur_snapshot: dict[str, Any] = {}

    for fname, fpath in cur_files.items():
        text = read_text(fpath)
        fm, _ = parse_fm(text)
        fm = fm or {}
        sync_mode = fm.get("sync", "auto")
        redacted = sync_mode == "never"
        sha = sha256_file(fpath)
        rec: dict[str, Any] = {
            "sha256": sha,
            "updated": fm.get("updated", ""),
            "type": fm.get("type", ""),
            "description": fm.get("description", ""),
            "digest": fm.get("digest", ""),
            "sync": sync_mode,
            "redacted": redacted,
        }
        if not redacted:
            rec["text"] = text
        cur_snapshot[fname] = rec

        if fname not in prev_mems:
            new_items.append((fname, rec, "[sync:never redacted - summary/pointer only]" if redacted else text))
        elif sha != prev_mems[fname].get("sha256"):
            old_txt = prev_mems[fname].get("text", "")
            inline_deltas: list[str] = []
            cur_body = "" if redacted else text
            if redacted or prev_mems[fname].get("redacted"):
                diff_txt = f"[sync:never pointer updated, updated={rec['updated']}, desc={rec['description']}]"
                cur_body = ""
            elif old_txt:
                diff_txt = build_contextual_diff(old_txt, text, fname)
                inline_deltas = extract_inline_deltas(old_txt, text)
            else:
                diff_txt = text
            mod_items.append((fname, rec, diff_txt, cur_body, inline_deltas))

    for fname, old_rec in sorted(prev_mems.items()):
        if fname not in cur_files:
            del_items.append((fname, old_rec))

    if sc["kind"] == "project" and not sc.get("manage_agents", True):
        agents_sha = ""
        agents_missing_or_drifted = False
    else:
        agents_sha = sha256_file(sc["agents"])
        agents_missing_or_drifted = (not sc["agents"].exists()) or (
            agents_sha != prev_scope_state.get("agents_sha256", "")
        )
    changed = bool(new_items or mod_items or del_items or agents_missing_or_drifted)
    return {
        "changed": changed,
        "mem_changed": bool(new_items or mod_items or del_items),
        "agents_missing_or_drifted": agents_missing_or_drifted,
        "new": new_items,
        "mod": mod_items,
        "del": del_items,
        "snapshot": cur_snapshot,
        "agents_sha": agents_sha,
    }


def write_diff_block(r: Report, sc: dict[str, Any], diff_info: dict[str, Any]) -> None:
    if diff_info["new"]:
        r.h("New Memories ([NEW])")
        for fname, rec, body in diff_info["new"]:
            fpath = sc["mem_dir"] / fname
            r.raw(f"\n### [NEW] {fname}")
            r.raw(f"- Meta: path=`{fpath}` | type={rec.get('type') or '-'} | updated={rec.get('updated') or '-'}")
            if rec.get("description"):
                r.raw(f"- Description: {rec['description']}")
            if rec.get("digest"):
                r.raw(f"- Digest: {rec['digest']}")
            r.raw("\n" + fence_block(body, "markdown"))
    if diff_info["mod"]:
        r.h("Modified Memories ([MODIFIED])")
        for fname, rec, dtxt, cur_body, inline_deltas in diff_info["mod"]:
            fpath = sc["mem_dir"] / fname
            r.raw(f"\n### [MODIFIED] {fname}")
            r.raw(f"- Meta: path=`{fpath}` | type={rec.get('type') or '-'} | updated={rec.get('updated') or '-'}")
            if rec.get("description"):
                r.raw(f"- Description: {rec['description']}")
            if rec.get("digest"):
                r.raw(f"- Digest: {rec['digest']}")
            r.raw(f"- Inspect full text: `memsync show {sc['id']} {fname} --version both`")
            if inline_deltas:
                r.raw("\n#### Inline Change Hints\n" + "\n".join(inline_deltas))
            r.raw("\n" + fence_block(dtxt, "diff"))
            if (not rec.get("redacted")) and cur_body and dtxt != cur_body:
                cbytes = nbytes(cur_body)
                if cbytes <= SMALL_MOD_FULLTEXT_BYTES:
                    r.raw(
                        f"\n#### Updated Full Body ({cbytes:,} bytes <= 4 KB; inlined for accuracy)\n"
                        + fence_block(cur_body, "markdown")
                    )
                else:
                    r.raw(
                        f"\n> Body is {cbytes:,} bytes. If any diff line is ambiguous, inspect via "
                        f"`memsync show {sc['id']} {fname} --version current` or `--version both`."
                    )
    if diff_info["del"]:
        r.h("Deleted Memories ([DELETED] - remove stale claims from AGENTS.md)")
        for fname, old_rec in diff_info["del"]:
            r.raw(f"\n### [DELETED] {fname}")
            r.i(
                f"Previous meta: type={old_rec.get('type') or '-'} | updated={old_rec.get('updated') or '-'} | "
                f"description: {old_rec.get('description', '')}"
            )
            if old_rec.get("digest"):
                r.i(f"Previous digest: {old_rec['digest']}")
            if old_rec.get("redacted") or old_rec.get("sync") == "never":
                r.i("Entry was sync: never (no cached body)")
            else:
                r.i(f"Inspect pre-delete full text: `memsync show {sc['id']} {fname} --version before`")


def cmd_sync_plan(_) -> int:
    cfg = load_config()
    plan = Report("Incremental Sync Plan (Stage 1: Workspaces -> Stage 2: Global)")
    if not cfg.get("mode", {}).get("agents_cache_enabled", True):
        plan.i("SKIP_ALL: index-only mode is active (mode.agents_cache_enabled=false); AGENTS.md sync disabled.")
        rc = plan.save("sync-plan")
        print("ws_update=none global_update=no mode=index-only")
        return rc

    st = load_state()
    scopes_state = st.get("scopes", {})
    scopes = make_scopes(cfg, only_enabled=True)
    ws_scopes = [sc for sc in scopes if sc["kind"] == "project"]
    gl_scope = scopes[0]

    ws_to_update: list[str] = []
    prev_gl_ws = scopes_state.get("global", {}).get("workspace_agents_sha256", {})

    plan.h("Stage 1 · Per-Workspace Incremental Diff")
    for sc in ws_scopes:
        if not sc["root"].is_dir():
            plan.w(f"[{sc['id']}] workspace directory missing ({sc['root']}), skipped")
            continue
        if not sc.get("manage_agents", True):
            gl_dirty = workspace_global_fingerprint(sc) != prev_gl_ws.get(sc["id"], "")
            note = "memories/index changed; folded into global summary" if gl_dirty else "0 changes"
            plan.i(f"[{sc['id']}] SKIP_AGENTS (manage_agents=false; {note})")
            continue
        diff = scan_memories_diff(sc, scopes_state.get(sc["id"], {}))
        if not diff["changed"]:
            plan.i(f"[{sc['id']}] SKIP (0 changes)")
            continue
        ws_to_update.append(sc["id"])
        foreign_agents = sc["agents"].exists() and not is_memsync_agents(read_text(sc["agents"]))
        bundle_path = WORK / f"sync-ws-{sc['id']}-{today_date()}.md"
        ws_rep = Report(f"Workspace Incremental Input · {sc['id']} ({sc['root']})")
        ws_rep.i(f"Summary: {sc['summary']}")
        ws_rep.i(
            f"Current AGENTS.md: {'foreign (backup before overwrite)' if foreign_agents else ('present' if sc['agents'].exists() else 'initial creation')}"
        )
        if foreign_agents:
            ws_rep.w("FOREIGN_AGENTS: existing AGENTS.md was not generated by memsync; backup kept in backup/ before overwrite.")
        if sc["agents"].exists():
            ws_rep.h("Current Workspace AGENTS.md")
            ws_rep.raw("\n" + fence_block(read_text(sc["agents"]), "markdown"))
        write_diff_block(ws_rep, sc, diff)
        ws_rep.save(f"sync-ws-{sc['id']}")
        plan.i(
            f"[{sc['id']}] NEEDS_UPDATE (+{len(diff['new'])} ~{len(diff['mod'])} -{len(diff['del'])}"
            f"{' / missing-or-drifted' if diff['agents_missing_or_drifted'] else ''}"
            f"{' / FOREIGN_AGENTS' if foreign_agents else ''}) -> {bundle_path}"
        )

    gl_diff = scan_memories_diff(gl_scope, scopes_state.get("global", {}))
    ws_agents_changed = bool(ws_to_update) or any(
        workspace_global_fingerprint(sc) != prev_gl_ws.get(sc["id"], "")
        for sc in ws_scopes
        if sc["root"].is_dir()
    ) or set(sc["id"] for sc in ws_scopes) != set(prev_gl_ws.keys())

    global_needs = gl_diff["changed"] or ws_agents_changed
    plan.h("Stage 2 · Global Rollup Diff")
    if not global_needs:
        plan.i("[global] SKIP (0 changes across global and workspaces)")
    else:
        plan.i(
            f"[global] NEEDS_UPDATE (global +{len(gl_diff['new'])} ~{len(gl_diff['mod'])} "
            f"-{len(gl_diff['del'])}; workspace_changed={ws_agents_changed})"
        )
        plan.i("After completing Stage 1 apply calls, run: memsync.py global-input")

    rc = plan.save("sync-plan")
    print(f"ws_update={','.join(ws_to_update) or 'none'} global_update={'yes' if global_needs else 'no'}")
    return rc


def cmd_global_input(_) -> int:
    cfg = load_config()
    if not cfg.get("mode", {}).get("agents_cache_enabled", True):
        print("global-input skipped: index-only mode is active (agents_cache_enabled=false)")
        return 0
    st = load_state()
    scopes = make_scopes(cfg, only_enabled=True)
    gl_scope = scopes[0]
    ws_scopes = [sc for sc in scopes if sc["kind"] == "project"]
    prev_gl_st = st.get("scopes", {}).get("global", {})
    prev_gl_ws = prev_gl_st.get("workspace_agents_sha256", {})
    prev_gl_ws_texts = prev_gl_st.get("workspace_agents_text", {})
    gl_diff = scan_memories_diff(gl_scope, prev_gl_st)

    r = Report("Global AGENTS.md Stage-2 Input Bundle")
    r.h("Registered Workspaces & Stage-1 Delta Summary")
    active_ws_ids: set[str] = set()
    for sc in ws_scopes:
        active_ws_ids.add(sc["id"])
        cur_fp = workspace_global_fingerprint(sc)
        prev_fp = prev_gl_ws.get(sc["id"], "")
        unchanged = bool(prev_fp) and (cur_fp == prev_fp)
        managed = sc.get("manage_agents", True)
        doc_name = "AGENTS.md" if managed else "GEMINI.md"
        doc_path = sc["agents"] if managed else sc["gemini"]

        if unchanged:
            r.raw(f"\n### [UNCHANGED] Workspace `{sc['id']}` ({sc['root']}) - summary: {sc['summary']}")
            r.i(f"No changes since last global sync; keep existing global summary (inspect full copy via `memsync show {sc['id']} {doc_name}`).")
            continue

        tag = "manage_agents=false; using GEMINI.md index" if not managed else "updated in Stage 1"
        r.raw(f"\n### [UPDATED] Workspace `{sc['id']}` ({sc['root']}) - summary: {sc['summary']} ({tag})")
        if not doc_path.exists():
            r.w(f"workspace {doc_name} missing")
            continue

        cur_txt = read_text(doc_path)
        prev_txt = prev_gl_ws_texts.get(sc["id"], "")
        if prev_txt and prev_txt != cur_txt and nbytes(cur_txt) > SMALL_MOD_FULLTEXT_BYTES:
            inline_deltas = extract_inline_deltas(prev_txt, cur_txt)
            ws_diff = build_contextual_diff(prev_txt, cur_txt, f"{sc['id']}/{doc_name}")
            r.i(
                f"Current {doc_name} is {nbytes(cur_txt):,} bytes; showing delta since last global sync "
                f"(inspect full snapshot via `memsync show {sc['id']} {doc_name}`)."
            )
            if inline_deltas:
                r.raw("\n#### Inline Change Hints\n" + "\n".join(inline_deltas))
            r.raw("\n" + fence_block(ws_diff, "diff"))
        else:
            r.raw("\n" + fence_block(cur_txt, "markdown"))

    for removed_id in sorted(set(prev_gl_ws.keys()) - active_ws_ids):
        r.raw(f"\n### [REMOVED/DISABLED] Workspace `{removed_id}`")
        r.i("Workspace was disabled or removed; review Section 2 of global AGENTS.md to prune or archive it.")

    if gl_scope["agents"].exists():
        r.h("Current Global AGENTS.md")
        r.raw("\n" + fence_block(read_text(gl_scope["agents"]), "markdown"))
    write_diff_block(r, gl_scope, gl_diff)
    return r.save("sync-global")


def validate_agents_draft(
    sc: dict[str, Any],
    text: str,
    r: Report,
    old_text: str = "",
    diff_info: dict[str, Any] | None = None,
) -> None:
    size = nbytes(text)
    lim = sc["limits"]
    hint = "keep <= 32KB if syncing to Codex" if sc["kind"] == "global" else "consider trimming to stay focused"
    _check_budget(r, f"target {sc['agents']}", size, lim["agents_warn"], lim["agents_hard"], warn_hint=hint)
    if SECRET_RE.search(text):
        r.e("draft matched secret pattern; write refused")
    if "GEMINI.md" not in text:
        r.e("draft missing pointer to GEMINI.md")
    low = text.lower()
    if not any(tok in low for tok in ("自动生成", "定时", "auto-generated", "do not edit")):
        r.e("draft header missing auto-generated / do-not-edit notice")

    has_zh_secs = ("一、" in text and "二、" in text)
    has_en_secs = ("## 1." in text and "## 2." in text)
    if not (has_zh_secs or has_en_secs):
        r.w("draft lacks standard numbered section headers (e.g. '## 1.' / '## 一、')")
    if sc["kind"] == "global" and (GLOBAL_MEM / "local-installed-tools.md").exists():
        if "local-installed-tools.md" not in text:
            r.w("global AGENTS.md missing pointer to existing memories/local-installed-tools.md")
    if sc["kind"] == "project" and sc["name"] not in text and str(sc["root"]) not in text:
        r.e("workspace AGENTS.md missing workspace name or root path anchor")

    today_str = str(today_date())
    if today_str not in text:
        r.w(f"draft does not contain today's date ({today_str}); verify sync timestamp header was refreshed")

    del_items = (diff_info or {}).get("del", [])
    if del_items:
        for fname, _ in del_items:
            stem = Path(fname).stem.lower()
            if fname.lower() in low or f"[[{stem}]]" in low:
                r.w(f"deleted memory '{fname}' still appears in draft; verify stale claims were removed")

    old_bytes = nbytes(old_text) if old_text else 0
    if old_bytes >= SHRINK_WARN_MIN_BYTES and size < int(old_bytes * SHRINK_WARN_RATIO) and not del_items:
        r.w(
            f"draft shrank by >30% ({old_bytes:,} -> {size:,} bytes) with 0 deleted memories; "
            "verify no sections were dropped accidentally"
        )


def cmd_apply(args) -> int:
    cfg = load_config()
    if not cfg.get("mode", {}).get("agents_cache_enabled", True):
        print("apply refused: index-only mode is active (mode.agents_cache_enabled=false)")
        return 2
    sc = find_scope(cfg, args.scope)
    if sc is None:
        print(f"apply error: unknown scope '{args.scope}'")
        return 2
    if sc["kind"] == "project" and not sc.get("manage_agents", True):
        print(f"apply refused: workspace '{sc['id']}' has manage_agents=false")
        return 2
    draft_path = Path(args.draft)
    if not draft_path.exists():
        print(f"apply error: draft not found: {draft_path}")
        return 2

    new_text = read_text(draft_path).replace("\r\n", "\n").strip() + "\n"
    old_text = read_text(sc["agents"]).replace("\r\n", "\n") if sc["agents"].exists() else ""
    st = load_state()
    pre_diff = scan_memories_diff(sc, st.get("scopes", {}).get(sc["id"], {}))

    r = Report(f"AGENTS.md apply · {sc['id']}" + (" (dry-run)" if args.dry_run else ""))
    validate_agents_draft(sc, new_text, r, old_text=old_text, diff_info=pre_diff)

    d = list(difflib.ndiff(old_text.splitlines(), new_text.splitlines()))
    add = sum(1 for x in d if x.startswith("+ "))
    rem = sum(1 for x in d if x.startswith("- "))
    r.i(f"line diff: +{add} / -{rem}")
    if r.err:
        return r.save(f"apply-{sc['id']}")

    r.h("diff (changed lines)")
    r.raw("\n" + fence_block("\n".join(x for x in d if x[:2] in ("+ ", "- ")), "diff"))

    if args.dry_run:
        pv = WORK / f"preview-{sc['id']}-{today_date()}.md"
        write_utf8_nobom(pv, new_text)
        r.i(f"dry-run preview saved: {pv}")
        return r.save(f"apply-{sc['id']}")

    bk = backup_file(sc["agents"], f"agents-{sc['id']}")
    write_utf8_nobom(sc["agents"], new_text)
    if bk:
        r.i(f"backed up previous version: {bk}")
    r.i(f"wrote: {sc['agents']}")

    st.setdefault("scopes", {})
    diff = scan_memories_diff(sc, st["scopes"].get(sc["id"], {}))
    scope_rec: dict[str, Any] = {
        "path": str(sc["root"]),
        "agents_sha256": sha256_file(sc["agents"]),
        "agents_text": new_text,
        "memories": diff["snapshot"],
    }
    if sc["id"] == "global":
        ws_list = [w for w in make_scopes(cfg, only_enabled=True) if w["kind"] == "project"]
        scope_rec["workspace_agents_sha256"] = {
            w["id"]: workspace_global_fingerprint(w)
            for w in ws_list
        }
        ws_texts: dict[str, str] = {}
        for w in ws_list:
            doc = w["agents"] if w.get("manage_agents", True) else w["gemini"]
            if doc.exists():
                ws_texts[w["id"]] = read_text(doc)
        scope_rec["workspace_agents_text"] = ws_texts
    st["scopes"][sc["id"]] = scope_rec
    st["last_sync"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_state(st)

    cts = cfg.get("cross_tool_sync", {})
    if (
        sc["id"] == "global"
        and not getattr(args, "no_copy", False)
        and cts.get("enabled", False)
        and cts.get("auto_copy_on_global_apply", True)
        and cts.get("targets")
    ):
        r.h("Cross-Tool Sync")
        run_copy_global(cfg, list(cts["targets"].keys()), r, dry_run=False)

    pruned = prune_work_files(WORK_KEEP_DAYS)
    if pruned:
        r.i(f"pruned {pruned} expired work report(s) older than {WORK_KEEP_DAYS} days")

    write_utf8_nobom(
        STATUS_FILE,
        json.dumps({"last_apply": st["last_sync"], "scope": sc["id"], "bytes": nbytes(new_text), "added": add, "removed": rem}, ensure_ascii=False),
    )
    return r.save(f"apply-{sc['id']}")


# -------------------------------------------------------- read-only inspect
def _safe_slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "item"


def _emit_readonly_report(kind: str, report_text: str, summary_line: str, to_stdout: bool) -> int:
    if to_stdout:
        ensure_utf8_stdio()
        print(report_text)
        return 0
    WORK.mkdir(parents=True, exist_ok=True)
    out = WORK / f"{kind}-{today_date()}.md"
    write_utf8_nobom(out, report_text)
    print(f"{summary_line} report={out}")
    return 0


def cmd_show(args) -> int:
    cfg = load_config()
    sc = find_scope(cfg, args.scope)
    if sc is None:
        print(f"show error: unknown scope '{args.scope}'")
        return 2

    raw_target = (args.target or "").strip()
    if not raw_target or any(sep in raw_target for sep in ("/", "\\")) or ".." in raw_target:
        print(f"show error: invalid target '{raw_target}' (plain filename only)")
        return 2

    st = load_state()
    prev_scope = st.get("scopes", {}).get(sc["id"], {})
    version = args.version
    low = raw_target.lower()
    lines = [f"# Read-Only Inspect · {sc['id']} / {raw_target} · {dt.datetime.now():%Y-%m-%d %H:%M}", ""]

    if low in ("agents", "agents.md", "gemini", "gemini.md"):
        is_agents = low.startswith("agents")
        doc_name = "AGENTS.md" if is_agents else "GEMINI.md"
        doc_path = sc["agents"] if is_agents else sc["gemini"]
        cur_txt = read_text(doc_path) if doc_path.exists() else ""
        prev_txt = prev_scope.get("agents_text", "") if is_agents else ""
        if not cur_txt and not prev_txt:
            print(f"show error: {doc_name} not found in scope '{sc['id']}'")
            return 2
        lines.append(f"- Scope: `{sc['id']}` (`{sc['root']}`)")
        lines.append(f"- File: `{doc_path}`")
        lines.append(f"- Version: `{version}`")
        if version in ("before", "both"):
            lines.append("\n## Previous Synced Version (before)")
            lines.append(fence_block(prev_txt, "markdown") if prev_txt else "- (no cached snapshot in sync-state.json)")
        if version in ("current", "both"):
            lines.append("\n## Current Version (current)")
            lines.append(fence_block(cur_txt, "markdown") if cur_txt else "- (file does not exist on disk)")
        if version == "both" and prev_txt and cur_txt and prev_txt != cur_txt:
            lines.append("\n## Diff")
            lines.append(fence_block(build_contextual_diff(prev_txt, cur_txt, doc_name), "diff"))
        return _emit_readonly_report(
            f"show-{_safe_slug(sc['id'])}-{_safe_slug(Path(doc_name).stem)}",
            "\n".join(lines),
            f"show: scope={sc['id']} target={doc_name} version={version} redacted=no",
            args.stdout,
        )

    fname = raw_target if raw_target.endswith(".md") else f"{raw_target}.md"
    fpath = sc["mem_dir"] / fname
    prev_rec = prev_scope.get("memories", {}).get(fname)
    cur_exists = fpath.exists()
    if not cur_exists and prev_rec is None:
        print(f"show error: memory '{fname}' not found in scope '{sc['id']}' (disk or sync-state)")
        return 2

    cur_txt = read_text(fpath) if cur_exists else ""
    cur_fm, _ = parse_fm(cur_txt) if cur_exists else (None, "")
    cur_fm = cur_fm or {}
    redacted = (
        cur_fm.get("sync") == "never"
        or bool(prev_rec and (prev_rec.get("redacted") or prev_rec.get("sync") == "never"))
    )

    lines.append(f"- Scope: `{sc['id']}` (`{sc['root']}`)")
    lines.append(f"- File: `{fpath}` (on_disk={'yes' if cur_exists else 'no'})")
    lines.append(f"- Version: `{version}` | sync:never redacted: {'yes' if redacted else 'no'}")

    if redacted:
        lines.append("\n## Redacted Metadata (sync: never body protected)")
        meta_src = cur_fm if cur_exists else (prev_rec or {})
        lines.append(f"- type: `{meta_src.get('type', '')}` | updated: `{meta_src.get('updated', '')}`")
        lines.append(f"- description: {meta_src.get('description', '')}")
        if meta_src.get("digest"):
            lines.append(f"- digest: {meta_src.get('digest', '')}")
        lines.append("- body: `[REDACTED: sync: never]`")
        return _emit_readonly_report(
            f"show-{_safe_slug(sc['id'])}-{_safe_slug(Path(fname).stem)}",
            "\n".join(lines),
            f"show: scope={sc['id']} target={fname} version={version} redacted=yes",
            args.stdout,
        )

    prev_txt = (prev_rec or {}).get("text", "")
    if version in ("before", "both"):
        lines.append("\n## Previous Synced Version (before)")
        lines.append(fence_block(prev_txt, "markdown") if prev_txt else "- (no previous cached body in sync-state.json)")
    if version in ("current", "both"):
        lines.append("\n## Current Version (current)")
        lines.append(
            fence_block(cur_txt, "markdown")
            if cur_exists
            else "- (deleted from disk; inspect pre-delete text with `--version before`)"
        )
    if version == "both" and prev_txt and cur_exists:
        if prev_txt == cur_txt:
            lines.append("\n## Diff\n- Current and previous synced versions are identical.")
        else:
            deltas = extract_inline_deltas(prev_txt, cur_txt)
            if deltas:
                lines.append("\n## Inline Change Hints\n" + "\n".join(deltas))
            lines.append("\n## Diff")
            lines.append(fence_block(build_contextual_diff(prev_txt, cur_txt, fname), "diff"))

    return _emit_readonly_report(
        f"show-{_safe_slug(sc['id'])}-{_safe_slug(Path(fname).stem)}",
        "\n".join(lines),
        f"show: scope={sc['id']} target={fname} version={version} redacted=no",
        args.stdout,
    )


def cmd_search(args) -> int:
    cfg = load_config()
    query = (args.query or "").strip()
    if not query:
        print("search error: empty query")
        return 2

    try:
        pat = re.compile(query if args.regex else re.escape(query), re.IGNORECASE)
    except re.error as exc:
        print(f"search error: invalid regex: {exc}")
        return 2

    if args.scope == "all":
        scopes = make_scopes(cfg, only_enabled=True)
    else:
        sc = find_scope(cfg, args.scope)
        if sc is None:
            print(f"search error: unknown scope '{args.scope}'")
            return 2
        scopes = [sc]

    st = load_state()
    max_matches = max(1, int(args.max_matches))
    hits: list[dict[str, Any]] = []
    truncated = False

    def _scan_text(scope_id: str, fname: str, status: str, text: str) -> None:
        nonlocal truncated
        flines = text.splitlines()
        for idx, ln in enumerate(flines):
            if pat.search(ln):
                if len(hits) >= max_matches:
                    truncated = True
                    return
                ctx_lo = max(0, idx - 1)
                ctx_hi = min(len(flines), idx + 2)
                snippet = "\n".join(f"L{k + 1}: {flines[k]}" for k in range(ctx_lo, ctx_hi))
                hits.append({
                    "scope": scope_id,
                    "file": fname,
                    "status": status,
                    "line": idx + 1,
                    "heading": _nearest_heading(flines, idx),
                    "snippet": snippet,
                })

    for sc in scopes:
        if truncated:
            break
        cur_names: set[str] = set()
        if sc["mem_dir"].exists():
            for fpath in sorted(sc["mem_dir"].glob("*.md")):
                if truncated:
                    break
                cur_names.add(fpath.name)
                txt = read_text(fpath)
                fm, _ = parse_fm(txt)
                fm = fm or {}
                if fm.get("sync") == "never":
                    safe_meta = "\n".join(
                        f"{k}: {fm.get(k, '')}" for k in ("name", "description", "digest") if fm.get(k)
                    )
                    _scan_text(sc["id"], fpath.name, "CURRENT/sync:never-meta-only", safe_meta)
                else:
                    _scan_text(sc["id"], fpath.name, "CURRENT", txt)

        prev_mems = st.get("scopes", {}).get(sc["id"], {}).get("memories", {})
        for fname, old_rec in sorted(prev_mems.items()):
            if truncated:
                break
            if fname in cur_names:
                continue
            if old_rec.get("redacted") or old_rec.get("sync") == "never":
                safe_meta = f"description: {old_rec.get('description', '')}\ndigest: {old_rec.get('digest', '')}"
                _scan_text(sc["id"], fname, "DELETED-BEFORE/sync:never-meta-only", safe_meta)
            elif old_rec.get("text"):
                _scan_text(sc["id"], fname, "DELETED-BEFORE", old_rec["text"])

    lines = [
        f"# Read-Only Memory Search · {dt.datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Query: `{query}` (mode: {'regex' if args.regex else 'literal case-insensitive'})",
        f"- Scope: `{args.scope}` | hits: {len(hits)}{' (truncated at max-matches)' if truncated else ''}",
        "- Privacy guard: `sync: never` entries are matched on safe metadata only; bodies are never read.",
    ]
    if not hits:
        lines.append("\n(no matches found)")
    else:
        for i, h in enumerate(hits, 1):
            head_note = f" | section: {h['heading']}" if h["heading"] else ""
            lines.append(f"\n### {i}. [{h['scope']}] `{h['file']}` ({h['status']} · L{h['line']}{head_note})")
            lines.append(fence_block(h["snippet"], "text"))

    return _emit_readonly_report(
        "search",
        "\n".join(lines),
        f"search: scope={args.scope} hits={len(hits)} truncated={'yes' if truncated else 'no'}",
        args.stdout,
    )


# ---------------------------------------------------------- workspaces & init
def update_global_gemini_workspaces(cfg: dict[str, Any]) -> bool:
    if not GLOBAL_GEMINI.exists():
        return False
    text = read_text(GLOBAL_GEMINI)
    lang = cfg.get("lang", "zh")
    tr = I18N.get(lang, I18N["zh"])

    start_match = None
    matched_ws_heading = tr["global_ws_heading"]
    for h in GLOBAL_WS_HEADINGS:
        m = re.search(rf"(?m)^{re.escape(h)}\s*$", text)
        if m:
            start_match = m
            matched_ws_heading = h
            break

    end_match = None
    for h in GLOBAL_INDEX_HEADINGS:
        m = re.search(rf"(?m)^{re.escape(h)}\s*$", text)
        if m:
            end_match = m
            break

    if not start_match or not end_match or end_match.start() <= start_match.start():
        return False

    i, j = start_match.start(), end_match.start()
    lines = [matched_ws_heading]
    for ws in cfg.get("workspaces", []):
        if ws.get("enabled", True):
            lines.append(f"- `{ws['name']}` (`{ws['path']}`): {ws['summary']}")
    ignored = cfg.get("ignored", [])
    if ignored:
        ign_paths = [f"`{x.get('path', x) if isinstance(x, dict) else x}`" for x in ignored]
        lines.append(f"- {tr['ignored_label']}: {', '.join(ign_paths)}")
    new_text = text[:i] + "\n".join(lines) + "\n\n" + text[j:]
    write_utf8_nobom(GLOBAL_GEMINI, new_text)
    return True


def infer_ws_summary(root: Path, name: str, lang: str = "zh") -> str:
    readme = root / "README.md"
    if readme.exists():
        for ln in read_text(readme).splitlines():
            s = ln.strip().lstrip("#").strip()
            if s:
                return s[:64]
    tr = I18N.get(lang, I18N["zh"])
    return tr["default_ws_summary"].format(name=name)


def ensure_gitignore_entry(root: Path, entry: str = ".gemini/memories/") -> str:
    if not (root / ".git").exists():
        return "skip(not-git)"
    gi = root / ".gitignore"
    accepted = {".gemini/memories", ".gemini/memories/", "/.gemini/memories", "/.gemini/memories/", ".gemini/", ".gemini"}
    existing = read_text(gi) if gi.exists() else ""
    if any(ln.strip() in accepted for ln in existing.splitlines()):
        return "already-present"
    new_text = existing
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    new_text += entry + "\n"
    write_utf8_nobom(gi, new_text)
    return "added"


def render_project_gemini(root: Path, name: str, cfg: dict[str, Any]) -> str:
    lang = cfg.get("lang", "zh")
    lim = get_budgets(cfg)["project"]
    mem_dir = root / ".gemini" / "memories"
    gw = lim["gemini_warn"] // 1000
    hw = lim["head_warn"] // 1000
    gh = lim["gemini_hard"] // 1000
    hh = lim["head_hard"] // 1000
    if lang == "en":
        return (
            f"# Project Memory · {root}\n\n"
            f"This file holds the memory index specific to `{name}` "
            f"(read/write protocol, entry types, and thresholds live in `{GLOBAL_GEMINI}`).\n"
            f"Memory body directory: `{mem_dir}`; recommended <= {gw}KB (header <= {hw}KB), hard cap {gh}KB/{hh}KB.\n\n"
            f"## Project Index\n"
        )
    return (
        f"# 项目记忆 · {root}\n\n"
        f"本文件只存 `{name}` 工作区独有记忆的索引（读写规程、分类与阈值详见 `{GLOBAL_GEMINI}`）。\n"
        f"正文目录：`{mem_dir}`；建议 <= {gw}KB（头部 <= {hw}KB），硬阻断 {gh}KB/{hh}KB。\n\n"
        f"## 项目索引\n"
    )


def render_project_agents_init(root: Path, name: str, summary: str, cfg: dict[str, Any]) -> str:
    lang = cfg.get("lang", "zh")
    sched_time = cfg.get("schedule", {}).get("time", "06:00")
    proj_gemini = root / "GEMINI.md"
    proj_mem = root / ".gemini" / "memories"
    if lang == "en":
        return (
            f"# AGENTS.md ({name} Workspace Snapshot)\n\n"
            f"> Auto-generated snapshot maintained via `memsync` ({sched_time} / on-demand). Do not edit manually.\n"
            f"> Workspace: {name} (`{root}`) | Summary: {summary} | Last synced: {today_date()}\n"
            f"> **Memory Entrypoints**: Project index at [{proj_gemini}]({proj_gemini}) (entries in `{proj_mem}`); "
            f"global rules & index at [{GLOBAL_GEMINI}]({GLOBAL_GEMINI}).\n\n"
            f"## 1. Active Project Progress & Decisions\n\n"
            f"- No project progress entries recorded yet (populated on next snapshot sync).\n\n"
            f"## 2. Project-Specific Conventions & Pitfalls\n\n"
            f"- No project-specific constraints recorded yet (general conventions live in global snapshot).\n"
        )
    return (
        f"# AGENTS.md（{name} 工作区快照）\n\n"
        f"> 由 **记忆同步任务（`memsync`，{sched_time} / 按需触发）** 自动生成并维护，严禁手工编辑。\n"
        f"> 所属工作区：{name}（`{root}`）｜定位：{summary}｜最近同步：{today_date()}\n"
        f"> **完整记忆入口**：本项目记忆索引与写入入口见 [{proj_gemini}]({proj_gemini})（正文在 `{proj_mem}`）；"
        f"跨项目全局规范与索引见 [{GLOBAL_GEMINI}]({GLOBAL_GEMINI})。\n\n"
        f"## 一、本项目主线进展与现状\n\n"
        f"- 暂无项目进度记忆（待对话沉淀并执行快照同步后填充）。\n\n"
        f"## 二、本项目专属规范与核心坑位\n\n"
        f"- 暂无项目专属规范（仅记录本项目独有约束，通用规范见全局快照）。\n"
    )


def render_global_gemini_minimal(cfg: dict[str, Any]) -> str:
    lang = cfg.get("lang", "zh")
    agents_on = bool(cfg.get("mode", {}).get("agents_cache_enabled", True))
    lim = get_budgets(cfg)["global"]
    if lang == "en":
        cache_line = (
            f"- **Hot Snapshot Cache**: `{GLOBAL_AGENTS}` and `<workspace>/AGENTS.md` are auto-generated snapshots maintained by `memsync`; never edit them by hand.\n"
            if agents_on
            else "- **Mode**: Index-only mode (`agents_cache_enabled=false`); no `AGENTS.md` snapshots are generated.\n"
        )
        return (
            f"# Memory System · Global Index\n\n"
            f"- **Core Operations**: `{OPS / 'memsync.py'}` (run `python3 \"{OPS / 'memsync.py'}\" lint` after memory updates).\n"
            f"- **Entries Directory**: `{GLOBAL_MEM}` (`user | feedback | project | reference`).\n"
            f"{cache_line}"
            f"- **Budgets**: Recommended <= {lim['gemini_warn'] // 1000}KB (header <= {lim['head_warn'] // 1000}KB), hard cap {lim['gemini_hard'] // 1000}KB/{lim['head_hard'] // 1000}KB.\n\n"
            f"## Rules\n"
            f"1. Read index first and load only needed memory files.\n"
            f"2. Write (two-stage): persist durable user-stated bans, corrections, permanent rules, and reusable agent-discovered pitfalls/workarounds immediately in the same turn/sub-step (unless already in a global Skill), and flush unwritten items at >=80% context alert or before compaction; curate remaining durable insights post-task, merging into existing topic files and updating `updated`.\n"
            f"3. Never store plain-text secrets; mark pointer files with `sync: never`.\n"
            f"4. Keep index entries formatted as `- [YYYY-MM-DD type·tag][Title](memories/<slug>.md) - concise summary`.\n\n"
            f"## Registered Workspaces\n\n"
            f"## Global Index\n"
        )
    cache_line = (
        f"- **热缓存快照**：`{GLOBAL_AGENTS}` 与 `<工作区>/AGENTS.md` 均由 `memsync` 自动维护，严禁手工编辑。\n"
        if agents_on
        else "- **运行模式**：极简纯索引模式（`agents_cache_enabled=false`），不生成 `AGENTS.md` 快照。\n"
    )
    return (
        f"# 记忆系统 · 全局索引与规程\n\n"
        f"- **运维脚本**：`{OPS / 'memsync.py'}`（每次增删改记忆正文后自动跑一次 `python \"{OPS / 'memsync.py'}\" lint` 自检）。\n"
        f"- **正文目录**：`{GLOBAL_MEM}`（四类：`user | feedback | project | reference`）。\n"
        f"{cache_line}"
        f"- **体积阈值**：建议 <= {lim['gemini_warn'] // 1000}KB（头部 <= {lim['head_warn'] // 1000}KB），硬阻断 {lim['gemini_hard'] // 1000}KB/{lim['head_hard'] // 1000}KB。\n\n"
        f"## 读写规程\n"
        f"1. 读：按需克制，先看索引再精准读取相关正文。\n"
        f"2. 写（双时机）：用户明确的禁用项/纠偏/长期约束与 Agent 自测实锤的高复用坑/绕行方案当轮即刻写入（已写全局 Skill 不双写），达 80% 预警或压缩前先抢救未落盘条目；其余经验收尾裁决写入，同主题查重合并并更新 `updated`。\n"
        f"3. 安全：严禁写入密钥明文，敏感指针文件标记 `sync: never`；git 仓必须忽略 `.gemini/memories/`。\n"
        f"4. 索引格式：`- 【YYYY-MM-DD 类型·定性】[标题](memories/<slug>.md) — 一句话结论`。\n\n"
        f"## 已注册工作区\n\n"
        f"## 全局索引\n"
    )


def render_global_agents_init(cfg: dict[str, Any]) -> str:
    lang = cfg.get("lang", "zh")
    sched_time = cfg.get("schedule", {}).get("time", "06:00")
    if lang == "en":
        return (
            f"# AGENTS.md (Global Snapshot)\n\n"
            f"> Auto-generated snapshot maintained via `memsync` ({sched_time} / on-demand). Do not edit manually.\n"
            f"> **Full Memory Entrypoint**: [{GLOBAL_GEMINI}]({GLOBAL_GEMINI}) | Entries directory: `{GLOBAL_MEM}`\n\n"
            f"## 1. User Profile & Core Preferences\n\n"
            f"- Not recorded yet.\n\n"
            f"## 2. Workspaces & Active Projects\n\n"
            f"- No workspaces synced yet.\n\n"
            f"## 3. General Engineering Conventions\n\n"
            f"- Not recorded yet.\n\n"
            f"## 4. Environment & Tooling Quick Reference\n\n"
            f"- Not recorded yet.\n"
        )
    return (
        f"# AGENTS.md（全局热缓存快照）\n\n"
        f"> 由 **记忆同步任务（`memsync`，{sched_time} / 按需触发）** 自动生成并维护，严禁手工编辑。\n"
        f"> **完整记忆入口**：[{GLOBAL_GEMINI}]({GLOBAL_GEMINI})，全部正文位于 `{GLOBAL_MEM}`。\n\n"
        f"## 一、用户基础信息与核心偏好\n\n"
        f"- 暂无全局偏好记忆。\n\n"
        f"## 二、各工作区定位与当前动态\n\n"
        f"- 暂无已同步工作区摘要。\n\n"
        f"## 三、通用开发规范与协作红线\n\n"
        f"- 暂无通用开发规范记忆。\n\n"
        f"## 四、本机常用工具与参考速查\n\n"
        f"- 暂无工具参考记忆。\n"
    )


def init_workspace(
    path_str: str,
    summary: str = "",
    name: str | None = None,
    allow_nested: bool = False,
    disabled: bool = False,
    force_agents: bool = False,
    no_manage_agents: bool = False,
) -> int:
    if force_agents and no_manage_agents:
        print("init error: --force-agents and --no-manage-agents are mutually exclusive")
        return 2
    p = Path(path_str).expanduser().resolve()
    if not p.is_dir():
        print(f"init error: directory does not exist: {p}")
        return 2
    cfg = load_config()
    lang = cfg.get("lang", "zh")
    agents_cache_on = bool(cfg.get("mode", {}).get("agents_cache_enabled", True))
    p_norm = norm_path(p)

    existing_ws = None
    for ws in cfg.get("workspaces", []):
        ex_norm = norm_path(ws["path"])
        if ex_norm == p_norm:
            existing_ws = ws
        elif not allow_nested and is_nested_path(p, ws["path"]):
            print(f"init refused: nested inside/parent of '{ws['name']}' ({ws['path']}). Use parent workspace or --allow-nested.")
            return 2

    ws_name = (name or (existing_ws["name"] if existing_ws else p.name)).strip().lower().replace(" ", "-")
    ws_summary = (summary or "").strip() or (existing_ws["summary"] if existing_ws else infer_ws_summary(p, ws_name, lang=lang))
    if no_manage_agents:
        manage_agents = False
    elif force_agents:
        manage_agents = True
    elif existing_ws is not None:
        manage_agents = existing_ws.get("manage_agents", True)
    else:
        manage_agents = True

    cfg["ignored"] = [
        item for item in cfg.get("ignored", [])
        if norm_path(item.get("path", "") if isinstance(item, dict) else str(item)) != p_norm
    ]

    (p / ".gemini" / "memories").mkdir(parents=True, exist_ok=True)

    proj_gemini = p / "GEMINI.md"
    gemini_status = "kept"
    if not proj_gemini.exists() or not read_text(proj_gemini).strip():
        write_utf8_nobom(proj_gemini, render_project_gemini(p, ws_name, cfg))
        gemini_status = "created"

    proj_agents = p / "AGENTS.md"
    agents_status = "kept"
    if not agents_cache_on:
        agents_status = "skipped(index-only mode; existing untouched)" if proj_agents.exists() else "skipped(index-only mode)"
    elif not manage_agents:
        agents_status = "unmanaged(manage_agents=false; existing AGENTS.md untouched)" if proj_agents.exists() else "unmanaged(manage_agents=false; not created)"
    elif not proj_agents.exists() or not read_text(proj_agents).strip():
        write_utf8_nobom(proj_agents, render_project_agents_init(p, ws_name, ws_summary, cfg))
        agents_status = "created"
    else:
        ag_txt = read_text(proj_agents)
        if not is_memsync_agents(ag_txt):
            if force_agents:
                backup_file(proj_agents, f"preinit-{ws_name}")
                write_utf8_nobom(proj_agents, render_project_agents_init(p, ws_name, ws_summary, cfg))
                agents_status = "replaced(backed-up)"
            else:
                agents_status = "preserved-foreign(WARN: non-memsync AGENTS.md kept; migrate then apply or pass --no-manage-agents)"

    gi_status = ensure_gitignore_entry(p)

    if existing_ws is not None:
        existing_ws["name"] = ws_name
        existing_ws["path"] = str(p)
        existing_ws["summary"] = ws_summary
        existing_ws["enabled"] = not disabled
        if manage_agents:
            existing_ws.pop("manage_agents", None)
        else:
            existing_ws["manage_agents"] = False
        reg_status = "updated"
    else:
        rec: dict[str, Any] = {
            "name": ws_name,
            "path": str(p),
            "summary": ws_summary,
            "enabled": not disabled,
        }
        if not manage_agents:
            rec["manage_agents"] = False
        cfg.setdefault("workspaces", []).append(rec)
        reg_status = "registered"

    save_config(cfg)
    update_global_gemini_workspaces(cfg)

    if agents_cache_on and manage_agents and proj_agents.exists() and is_memsync_agents(read_text(proj_agents)):
        st = load_state()
        scopes_st = st.setdefault("scopes", {})
        if ws_name not in scopes_st:
            scopes_st[ws_name] = {
                "path": str(p),
                "agents_sha256": sha256_file(proj_agents),
                "memories": {},
            }
            save_state(st)

    log("init", f"name={ws_name} reg={reg_status} manage_agents={manage_agents} gemini={gemini_status} agents={agents_status} gitignore={gi_status}")
    print(f"init: name={ws_name} path={p} reg={reg_status} manage_agents={manage_agents} gemini={gemini_status} agents={agents_status} gitignore={gi_status}")
    return 0


def cmd_bootstrap(args) -> int:
    OPS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    BACKUP.mkdir(parents=True, exist_ok=True)
    GLOBAL_MEM.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    if args.lang:
        cfg["lang"] = args.lang
    if args.agents_cache:
        cfg["mode"]["agents_cache_enabled"] = (args.agents_cache == "on")
        if not cfg["mode"]["agents_cache_enabled"]:
            cfg["mode"]["schedule_enabled"] = False
    if args.schedule:
        cfg["mode"]["schedule_enabled"] = (args.schedule == "on") and cfg["mode"]["agents_cache_enabled"]
    if args.auto_discover:
        cfg["mode"]["auto_discover_unregistered"] = (args.auto_discover == "on")
    if args.schedule_time:
        cfg["schedule"]["time"] = args.schedule_time
    if args.timezone:
        cfg["schedule"]["timezone"] = args.timezone
    if args.profile:
        cfg["limits"]["profile"] = args.profile
    if getattr(args, "context_hook", None):
        cfg["context_hook"]["enabled"] = (args.context_hook == "on")
    if getattr(args, "hook_mode", None):
        cfg["context_hook"]["mode"] = args.hook_mode
    if getattr(args, "hook_warn", None) is not None:
        cfg["context_hook"]["warn_percent"] = _clamp_warn_percent(args.hook_warn)
    if getattr(args, "hook_cooldown", None) is not None:
        cfg["context_hook"]["cooldown_calls"] = _clamp_cooldown(args.hook_cooldown)
    if getattr(args, "hook_critical", None) is not None:
        cfg["context_hook"]["critical_percent"] = _clamp_critical_percent(args.hook_critical)
    if args.target:
        targets = cfg.setdefault("cross_tool_sync", {}).setdefault("targets", {})
        for spec in args.target:
            if "=" not in spec:
                print(f"bootstrap error: invalid --target '{spec}', expected name=path")
                return 2
            k, v = spec.split("=", 1)
            targets[k.strip()] = str(Path(v.strip()).expanduser())
        cfg["cross_tool_sync"]["enabled"] = True

    save_config(cfg)

    g_stat = "skipped"
    a_stat = "skipped"
    if not args.no_global_files:
        if not GLOBAL_GEMINI.exists() or not read_text(GLOBAL_GEMINI).strip() or args.force_global:
            if GLOBAL_GEMINI.exists():
                backup_file(GLOBAL_GEMINI, "preboot-global-gemini")
            write_utf8_nobom(GLOBAL_GEMINI, render_global_gemini_minimal(cfg))
            g_stat = "written"
        else:
            g_stat = "kept-existing"

        if cfg["mode"]["agents_cache_enabled"]:
            if not GLOBAL_AGENTS.exists() or not read_text(GLOBAL_AGENTS).strip() or args.force_global:
                if GLOBAL_AGENTS.exists():
                    backup_file(GLOBAL_AGENTS, "preboot-global-agents")
                write_utf8_nobom(GLOBAL_AGENTS, render_global_agents_init(cfg))
                a_stat = "written"
            else:
                a_stat = "kept-existing"
        else:
            a_stat = "disabled(index-only)"

    hook_stat = "disabled"
    if cfg.get("context_hook", {}).get("enabled"):
        ok_hook, hook_msg = install_context_hook(cfg)
        if not ok_hook:
            print(f"bootstrap error: {hook_msg}")
            return 2
        hook_stat = "installed"

    print(f"bootstrap: config={CONFIG_FILE} lang={cfg['lang']} profile={cfg['limits']['profile']} global_gemini={g_stat} global_agents={a_stat} context_hook={hook_stat}")
    return 0


def cmd_config(args) -> int:
    cfg = load_config()
    if args.cfg_cmd == "show":
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return 0
    if args.cfg_cmd == "set":
        if args.lang:
            cfg["lang"] = args.lang
        if args.agents_cache:
            cfg["mode"]["agents_cache_enabled"] = (args.agents_cache == "on")
            if not cfg["mode"]["agents_cache_enabled"]:
                cfg["mode"]["schedule_enabled"] = False
        if args.schedule:
            if args.schedule == "on" and not cfg["mode"]["agents_cache_enabled"]:
                print("config error: cannot enable schedule while agents-cache is off")
                return 2
            cfg["mode"]["schedule_enabled"] = (args.schedule == "on")
        if args.auto_discover:
            cfg["mode"]["auto_discover_unregistered"] = (args.auto_discover == "on")
        if args.profile:
            cfg["limits"]["profile"] = args.profile
        if args.context_hook:
            cfg["context_hook"]["enabled"] = (args.context_hook == "on")
        if args.hook_mode:
            cfg["context_hook"]["mode"] = args.hook_mode
        if args.hook_warn is not None:
            cfg["context_hook"]["warn_percent"] = _clamp_warn_percent(args.hook_warn)
        if args.hook_cooldown is not None:
            cfg["context_hook"]["cooldown_calls"] = _clamp_cooldown(args.hook_cooldown)
        if args.hook_critical is not None:
            cfg["context_hook"]["critical_percent"] = _clamp_critical_percent(args.hook_critical)
        if args.cross_sync:
            cfg["cross_tool_sync"]["enabled"] = (args.cross_sync == "on")
        if args.add_target:
            for spec in args.add_target:
                if "=" not in spec:
                    print(f"config error: invalid --add-target '{spec}', expected name=path")
                    return 2
                k, v = spec.split("=", 1)
                cfg["cross_tool_sync"].setdefault("targets", {})[k.strip()] = str(Path(v.strip()).expanduser())
        if args.remove_target:
            for k in args.remove_target:
                cfg.get("cross_tool_sync", {}).get("targets", {}).pop(k, None)
        save_config(cfg)
        print(f"config updated: {CONFIG_FILE}")
        return 0
    return 2


def cmd_init(args) -> int:
    return init_workspace(
        args.path,
        summary=args.summary or "",
        name=args.name,
        allow_nested=args.allow_nested,
        disabled=args.disabled,
        force_agents=args.force_agents,
        no_manage_agents=args.no_manage_agents,
    )


def cmd_ws(args) -> int:
    cfg = load_config()
    tr = I18N.get(cfg.get("lang", "zh"), I18N["zh"])
    if args.ws_cmd == "list":
        cts = cfg.get("cross_tool_sync", {})
        print(f"mode={json.dumps(cfg['mode'])} profile={cfg['limits']['profile']} lang={cfg['lang']}")
        print(f"cross_tool_sync.enabled={cts.get('enabled', False)} auto_copy={cts.get('auto_copy_on_global_apply', True)}")
        print("Registered workspaces:")
        for ws in cfg.get("workspaces", []):
            flags = ["enabled" if ws.get("enabled", True) else "disabled"]
            if not ws.get("manage_agents", True):
                flags.append("manage_agents=false")
            print(f"  - {ws['name']} [{', '.join(flags)}] path={ws['path']} summary={ws['summary']}")
        print("Ignored paths:")
        for item in cfg.get("ignored", []):
            p = item.get("path", item) if isinstance(item, dict) else item
            rs = item.get("reason", "") if isinstance(item, dict) else ""
            print(f"  - {p}" + (f" ({rs})" if rs else ""))
        print("Copy targets:")
        for k, v in cts.get("targets", {}).items():
            print(f"  - {k}: {v}")
        return 0

    if args.ws_cmd == "add":
        return init_workspace(
            args.path,
            summary=args.summary or "",
            name=args.name,
            allow_nested=args.allow_nested,
            disabled=args.disabled,
            force_agents=args.force_agents,
            no_manage_agents=args.no_manage_agents,
        )

    if args.ws_cmd == "ignore":
        p = Path(args.path).expanduser().resolve()
        p_norm = norm_path(p)
        if p_norm not in ignored_norms(cfg):
            cfg.setdefault("ignored", []).append({
                "path": str(p),
                "reason": args.reason or tr["default_ignore_reason"],
                "added": str(today_date()),
            })
            save_config(cfg)
            update_global_gemini_workspaces(cfg)
            log("ws-ignore", f"path={p}")
        print(f"ws ignored: {p}")
        return 0

    if args.ws_cmd == "unignore":
        p_norm = norm_path(Path(args.path).expanduser().resolve())
        before = len(cfg.get("ignored", []))
        cfg["ignored"] = [
            item for item in cfg.get("ignored", [])
            if norm_path(item.get("path", "") if isinstance(item, dict) else str(item)) != p_norm
        ]
        save_config(cfg)
        update_global_gemini_workspaces(cfg)
        print(f"ws unignored: {args.path} (removed={before - len(cfg['ignored'])})")
        return 0

    if args.ws_cmd in ("enable", "disable"):
        want_low = args.target.lower()
        want_norm = norm_path(args.target) if Path(args.target).expanduser().exists() else want_low.rstrip("\\/")
        for ws in cfg.get("workspaces", []):
            if ws["name"].lower() == want_low or norm_path(ws["path"]) == want_norm:
                ws["enabled"] = args.ws_cmd == "enable"
                save_config(cfg)
                update_global_gemini_workspaces(cfg)
                print(f"ws {args.ws_cmd}d: {ws['name']}")
                return 0
        print(f"ws {args.ws_cmd} error: workspace not found: {args.target}")
        return 2

    if args.ws_cmd == "manage-agents":
        want_low = args.target.lower()
        want_norm = norm_path(args.target) if Path(args.target).expanduser().exists() else want_low.rstrip("\\/")
        for ws in cfg.get("workspaces", []):
            if ws["name"].lower() == want_low or norm_path(ws["path"]) == want_norm:
                if args.on:
                    ws.pop("manage_agents", None)
                else:
                    ws["manage_agents"] = False
                save_config(cfg)
                log("ws-manage-agents", f"name={ws['name']} manage_agents={args.on}")
                print(f"ws manage-agents: {ws['name']} manage_agents={args.on}")
                return 0
        print(f"ws manage-agents error: workspace not found: {args.target}")
        return 2
    return 2


def _clamp_percent(val: float | int, lo: float, hi: float) -> int | float:
    p = max(lo, min(hi, float(val)))
    return int(p) if p.is_integer() else p


def _clamp_warn_percent(val: float | int) -> int | float:
    return _clamp_percent(val, 1.0, 99.0)


def _clamp_critical_percent(val: float | int) -> int | float:
    if float(val) <= 0:
        return 0
    return _clamp_percent(val, 1.0, 100.0)


def _clamp_cooldown(val: float | int) -> int:
    return max(1, int(val))


def _resolve_hook_script(script_src: str | None = None) -> Path | None:
    if script_src:
        cand = Path(script_src).expanduser().resolve()
        return cand if cand.is_file() else None
    for cand in (Path(__file__).resolve().parent / "context_hook.py", OPS / "context_hook.py"):
        if cand.is_file():
            return cand.resolve()
    return None


def _resolve_python_exe(py_cmd: str | None = None) -> str:
    if not py_cmd:
        return sys.executable
    cand = Path(py_cmd).expanduser()
    if cand.is_file():
        return str(cand.resolve())
    found = shutil.which(py_cmd)
    return found or py_cmd


def _format_hook_command(py_exe: str, script_path: Path) -> str:
    if platform.system() == "Windows":
        return f'call "{py_exe}" "{script_path}"'
    return f'"{py_exe}" "{script_path}"'


def install_context_hook(
    cfg: dict[str, Any],
    *,
    py_cmd: str | None = None,
    script_src: str | None = None,
    mode: str | None = None,
    warn_percent: float | int | None = None,
    cooldown_calls: int | None = None,
    critical_percent: float | int | None = None,
) -> tuple[bool, str]:
    src = _resolve_hook_script(script_src)
    if src is None:
        return False, "context_hook.py not found next to memsync.py or in memory-ops"

    OPS.mkdir(parents=True, exist_ok=True)
    dst_script = (OPS / "context_hook.py").resolve()
    new_code = src.read_text(encoding="utf-8")
    if dst_script != src:
        if dst_script.exists() and read_text(dst_script) != new_code:
            backup_file(dst_script, "prehook-script")
        write_utf8_nobom(dst_script, new_code)

    py_exe = _resolve_python_exe(py_cmd)
    cmd_str = _format_hook_command(py_exe, dst_script)
    plugin_meta = {
        "name": CONTEXT_HOOK_PLUGIN_ID,
        "displayName": "MilkFrog Context Monitor",
        "version": "0.1.0",
        "description": "PreInvocation hook that injects live context token occupancy and high-water memory rescue reminders.",
    }
    hooks_cfg = {
        "milkfrog-context-monitor": {
            "PreInvocation": [
                {
                    "type": "command",
                    "command": cmd_str,
                    "timeout": 5,
                }
            ]
        }
    }

    CONTEXT_HOOK_PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    plugin_json_path = CONTEXT_HOOK_PLUGIN_DIR / "plugin.json"
    hooks_json_path = CONTEXT_HOOK_PLUGIN_DIR / "hooks.json"
    plugin_txt = json.dumps(plugin_meta, ensure_ascii=False, indent=2) + "\n"
    hooks_txt = json.dumps(hooks_cfg, ensure_ascii=False, indent=2) + "\n"
    if plugin_json_path.exists() and read_text(plugin_json_path) != plugin_txt:
        backup_file(plugin_json_path, "prehook-plugin")
    if hooks_json_path.exists() and read_text(hooks_json_path) != hooks_txt:
        backup_file(hooks_json_path, "prehook-hooks")
    write_utf8_nobom(plugin_json_path, plugin_txt)
    write_utf8_nobom(hooks_json_path, hooks_txt)

    hook_cfg = cfg.setdefault("context_hook", {})
    hook_cfg["enabled"] = True
    if mode in ("always", "threshold"):
        hook_cfg["mode"] = mode
    if warn_percent is not None:
        hook_cfg["warn_percent"] = _clamp_warn_percent(warn_percent)
    if cooldown_calls is not None:
        hook_cfg["cooldown_calls"] = _clamp_cooldown(cooldown_calls)
    if critical_percent is not None:
        hook_cfg["critical_percent"] = _clamp_critical_percent(critical_percent)
    save_config(cfg)
    log(
        "hook-install",
        f"plugin={CONTEXT_HOOK_PLUGIN_DIR} mode={hook_cfg.get('mode')} "
        f"warn={hook_cfg.get('warn_percent')} cooldown={hook_cfg.get('cooldown_calls')} "
        f"critical={hook_cfg.get('critical_percent')}",
    )
    return True, f"plugin={CONTEXT_HOOK_PLUGIN_DIR} script={dst_script}"


def uninstall_context_hook(cfg: dict[str, Any]) -> str:
    hooks_json = CONTEXT_HOOK_PLUGIN_DIR / "hooks.json"
    if hooks_json.exists():
        backup_file(hooks_json, "uninstall-hooks")
    if CONTEXT_HOOK_PLUGIN_DIR.exists():
        shutil.rmtree(CONTEXT_HOOK_PLUGIN_DIR)
    cfg.setdefault("context_hook", {})["enabled"] = False
    save_config(cfg)
    log("hook-uninstall", f"removed={CONTEXT_HOOK_PLUGIN_DIR}")
    return f"removed={CONTEXT_HOOK_PLUGIN_DIR}"


def cmd_hook(args) -> int:
    cfg = load_config()
    if args.hook_cmd == "install":
        ok, msg = install_context_hook(
            cfg,
            py_cmd=args.python,
            script_src=args.script,
            mode=args.mode,
            warn_percent=args.warn_percent,
            cooldown_calls=args.cooldown,
            critical_percent=args.critical_percent,
        )
        if not ok:
            print(f"hook install error: {msg}")
            return 2
        h = cfg["context_hook"]
        print(
            f"hook installed: {msg} mode={h['mode']} warn_percent={h['warn_percent']} "
            f"cooldown_calls={h['cooldown_calls']} critical_percent={h['critical_percent']}"
        )
        return 0
    if args.hook_cmd == "status":
        h = cfg.get("context_hook", {})
        installed = (CONTEXT_HOOK_PLUGIN_DIR / "hooks.json").exists()
        script_ok = (OPS / "context_hook.py").exists()
        print(
            f"context_hook enabled={h.get('enabled', False)} installed={installed} "
            f"script={script_ok} mode={h.get('mode', 'threshold')} warn_percent={h.get('warn_percent', 80)} "
            f"cooldown_calls={h.get('cooldown_calls', 3)} critical_percent={h.get('critical_percent', 92)} "
            f"plugin_dir={CONTEXT_HOOK_PLUGIN_DIR}"
        )
        return 0
    if args.hook_cmd == "uninstall":
        msg = uninstall_context_hook(cfg)
        print(f"hook uninstalled: {msg}")
        return 0
    return 2


# ----------------------------------------------------------- copy-global
def run_copy_global(cfg: dict[str, Any], wanted: list[str], r: Report, dry_run: bool = False) -> None:
    if not GLOBAL_AGENTS.exists() or GLOBAL_AGENTS.stat().st_size == 0:
        r.e(f"cross-tool source file missing or empty: {GLOBAL_AGENTS}")
        return
    targets = cfg.get("cross_tool_sync", {}).get("targets", {})
    src_text = read_text(GLOBAL_AGENTS)
    r.i(f"source: {GLOBAL_AGENTS} ({nbytes(src_text)} bytes)")
    for name in wanted:
        dst = Path(targets[name]).expanduser()
        if dry_run:
            r.i(f"[{name}] dry-run would write {dst}")
            continue
        bk = backup_file(dst, f"copy-{name}")
        write_utf8_nobom(dst, src_text)
        note = f" (backup: {bk.name})" if bk else ""
        if name == "codex" and platform.system() == "Windows":
            note += "; verify loading inside Codex with /status"
        r.i(f"[{name}] wrote {dst}{note}")


def cmd_copy_global(args) -> int:
    cfg = load_config()
    if not cfg.get("mode", {}).get("agents_cache_enabled", True):
        print("copy-global refused: index-only mode is active (agents_cache_enabled=false)")
        return 2
    if not GLOBAL_AGENTS.exists() or GLOBAL_AGENTS.stat().st_size == 0:
        print(f"copy-global error: source missing or empty: {GLOBAL_AGENTS}")
        return 2
    targets = cfg.get("cross_tool_sync", {}).get("targets", {})
    wanted = [x.strip() for x in args.targets.split(",") if x.strip()] if args.targets else list(targets.keys())
    if not wanted:
        print("copy-global skipped: no cross_tool_sync targets configured")
        return 0
    unknown = [x for x in wanted if x not in targets]
    if unknown:
        print(f"copy-global error: unknown target(s): {','.join(unknown)}")
        return 2

    r = Report("Global AGENTS.md Cross-Tool Sync" + (" (dry-run)" if args.dry_run else ""))
    run_copy_global(cfg, wanted, r, dry_run=args.dry_run)
    return r.save("copy-global")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="MilkFrog dual-layer memory system utility")
    sp = ap.add_subparsers(dest="cmd", required=True)

    ap_doc = sp.add_parser("doctor")
    ap_doc.add_argument("--json", action="store_true")

    ap_boot = sp.add_parser("bootstrap")
    ap_boot.add_argument("--lang", choices=["zh", "en"])
    ap_boot.add_argument("--agents-cache", choices=["on", "off"])
    ap_boot.add_argument("--schedule", choices=["on", "off"])
    ap_boot.add_argument("--auto-discover", choices=["on", "off"])
    ap_boot.add_argument("--schedule-time")
    ap_boot.add_argument("--timezone")
    ap_boot.add_argument("--profile", choices=list(BUDGET_PROFILES))
    ap_boot.add_argument("--context-hook", choices=["on", "off"])
    ap_boot.add_argument("--hook-mode", choices=["always", "threshold"])
    ap_boot.add_argument("--hook-warn", type=float)
    ap_boot.add_argument("--hook-cooldown", type=int)
    ap_boot.add_argument("--hook-critical", type=float)
    ap_boot.add_argument("--target", action="append", default=[])
    ap_boot.add_argument("--no-global-files", action="store_true")
    ap_boot.add_argument("--force-global", action="store_true")

    ap_cfg = sp.add_parser("config")
    cfg_sp = ap_cfg.add_subparsers(dest="cfg_cmd", required=True)
    cfg_sp.add_parser("show")
    cfg_set = cfg_sp.add_parser("set")
    cfg_set.add_argument("--lang", choices=["zh", "en"])
    cfg_set.add_argument("--agents-cache", choices=["on", "off"])
    cfg_set.add_argument("--schedule", choices=["on", "off"])
    cfg_set.add_argument("--auto-discover", choices=["on", "off"])
    cfg_set.add_argument("--profile", choices=list(BUDGET_PROFILES))
    cfg_set.add_argument("--context-hook", choices=["on", "off"])
    cfg_set.add_argument("--hook-mode", choices=["always", "threshold"])
    cfg_set.add_argument("--hook-warn", type=float)
    cfg_set.add_argument("--hook-cooldown", type=int)
    cfg_set.add_argument("--hook-critical", type=float)
    cfg_set.add_argument("--cross-sync", choices=["on", "off"])
    cfg_set.add_argument("--add-target", action="append", default=[])
    cfg_set.add_argument("--remove-target", action="append", default=[])

    sp.add_parser("lint")
    sp.add_parser("sync-plan")
    sp.add_parser("global-input")

    ap_apply = sp.add_parser("apply")
    ap_apply.add_argument("--scope", required=True)
    ap_apply.add_argument("draft")
    ap_apply.add_argument("--dry-run", action="store_true")
    ap_apply.add_argument("--no-copy", action="store_true")

    ap_show = sp.add_parser("show")
    ap_show.add_argument("scope")
    ap_show.add_argument("target")
    ap_show.add_argument("--version", choices=("current", "before", "both"), default="current")
    ap_show.add_argument("--stdout", action="store_true")

    ap_search = sp.add_parser("search")
    ap_search.add_argument("query")
    ap_search.add_argument("--scope", default="all")
    ap_search.add_argument("--max-matches", type=int, default=20)
    ap_search.add_argument("--regex", action="store_true")
    ap_search.add_argument("--stdout", action="store_true")

    ap_init = sp.add_parser("init")
    ap_init.add_argument("path")
    ap_init.add_argument("--summary", default="")
    ap_init.add_argument("--name")
    ap_init.add_argument("--disabled", action="store_true")
    ap_init.add_argument("--allow-nested", action="store_true")
    ap_init.add_argument("--force-agents", action="store_true")
    ap_init.add_argument("--no-manage-agents", action="store_true")

    ap_ws = sp.add_parser("ws")
    ws_sp = ap_ws.add_subparsers(dest="ws_cmd", required=True)
    ws_sp.add_parser("list")
    ws_add = ws_sp.add_parser("add")
    ws_add.add_argument("path")
    ws_add.add_argument("--summary", default="")
    ws_add.add_argument("--name")
    ws_add.add_argument("--disabled", action="store_true")
    ws_add.add_argument("--allow-nested", action="store_true")
    ws_add.add_argument("--force-agents", action="store_true")
    ws_add.add_argument("--no-manage-agents", action="store_true")
    ws_ign = ws_sp.add_parser("ignore")
    ws_ign.add_argument("path")
    ws_ign.add_argument("--reason", default="")
    ws_uni = ws_sp.add_parser("unignore")
    ws_uni.add_argument("path")
    for act in ("enable", "disable"):
        ws_t = ws_sp.add_parser(act)
        ws_t.add_argument("target")
    ws_ma = ws_sp.add_parser("manage-agents")
    ws_ma.add_argument("target")
    ma_grp = ws_ma.add_mutually_exclusive_group(required=True)
    ma_grp.add_argument("--on", action="store_true")
    ma_grp.add_argument("--off", action="store_true")

    ap_hk = sp.add_parser("hook")
    hk_sp = ap_hk.add_subparsers(dest="hook_cmd", required=True)
    hk_ins = hk_sp.add_parser("install")
    hk_ins.add_argument("--script", default="")
    hk_ins.add_argument("--python", default="")
    hk_ins.add_argument("--mode", choices=["always", "threshold"])
    hk_ins.add_argument("--warn-percent", type=float)
    hk_ins.add_argument("--cooldown", type=int)
    hk_ins.add_argument("--critical-percent", type=float)
    hk_sp.add_parser("status")
    hk_sp.add_parser("uninstall")

    ap_cp = sp.add_parser("copy-global")
    ap_cp.add_argument("--targets", default="")
    ap_cp.add_argument("--dry-run", action="store_true")

    return ap


def main() -> int:
    if sys.version_info < (3, 9):
        print("memsync requires Python 3.9+", file=sys.stderr)
        return 2
    args = build_parser().parse_args()
    handlers = {
        "doctor": cmd_doctor,
        "bootstrap": cmd_bootstrap,
        "config": cmd_config,
        "lint": cmd_lint,
        "sync-plan": cmd_sync_plan,
        "global-input": cmd_global_input,
        "apply": cmd_apply,
        "show": cmd_show,
        "search": cmd_search,
        "init": cmd_init,
        "ws": cmd_ws,
        "hook": cmd_hook,
        "copy-global": cmd_copy_global,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

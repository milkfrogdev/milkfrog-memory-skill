from __future__ import annotations

import datetime as dt
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
MEMSYNC_SCRIPT = SKILL_ROOT / "scripts" / "memsync.py"
CONTEXT_HOOK_SCRIPT = SKILL_ROOT / "scripts" / "context_hook.py"
EXAMPLES_DIR = SKILL_ROOT / "examples" / "milkfrog-demo"
TEMPLATES_DIR = SKILL_ROOT / "templates"


def run_memsync(mem_home: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MILKFROG_MEMORY_HOME"] = str(mem_home)
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, str(MEMSYNC_SCRIPT), *args],
        cwd=str(cwd or mem_home),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _pb_varint(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_bytes(field_no: int, payload: bytes) -> bytes:
    return _pb_varint((field_no << 3) | 2) + _pb_varint(len(payload)) + payload


def _pb_int(field_no: int, val: int) -> bytes:
    return _pb_varint(field_no << 3) + _pb_varint(val)


def make_gen_blob(uncached: int, cached: int, max_ctx: int, window_used: int = 0) -> bytes:
    usage = _pb_bytes(4, _pb_int(2, uncached) + _pb_int(5, cached))
    window_body = _pb_int(4, max_ctx) + (_pb_int(1, window_used) if window_used else b"")
    window_wrap = _pb_bytes(9, _pb_bytes(10, window_body))
    return _pb_bytes(1, usage + window_wrap)


class TestMilkFrogMemorySkill(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.mem_home = self.root / ".gemini"
        self.mem_home.mkdir(parents=True, exist_ok=True)
        self.ops = self.mem_home / "memory-ops"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_doctor_read_only_and_virtual_project_filtering(self) -> None:
        # Prepare foreign global GEMINI.md and Antigravity projects metadata
        (self.mem_home / "GEMINI.md").write_text("# My existing instructions\n", encoding="utf-8")
        proj_cfg = self.mem_home / "config" / "projects"
        proj_cfg.mkdir(parents=True, exist_ok=True)
        (self.mem_home / "config" / "config.json").write_text(
            json.dumps({"sidecars": {"cron1": {"projectId": "sidecar-pid"}}}),
            encoding="utf-8",
        )

        real_ws = self.root / "real_app"
        real_ws.mkdir()
        swarm_ws = self.mem_home / "antigravity" / "swarm" / "clone1"
        swarm_ws.mkdir(parents=True)
        sidecar_ws = self.root / "sidecar_ws"
        sidecar_ws.mkdir()

        (proj_cfg / "p1.json").write_text(
            json.dumps({
                "id": "real-pid",
                "projectResources": {"resources": [{"folderUri": real_ws.as_uri()}]},
            }),
            encoding="utf-8",
        )
        (proj_cfg / "p2.json").write_text(
            json.dumps({
                "id": "sidecar-pid",
                "sidecar": True,
                "projectResources": {"resources": [{"folderUri": sidecar_ws.as_uri()}]},
            }),
            encoding="utf-8",
        )
        (proj_cfg / "p3.json").write_text(
            json.dumps({
                "id": "swarm-pid",
                "projectResources": {"resources": [{"folderUri": swarm_ws.as_uri()}]},
            }),
            encoding="utf-8",
        )

        res = run_memsync(self.mem_home, "doctor", "--json", cwd=real_ws)
        self.assertEqual(res.returncode, 0, res.stderr)
        data = json.loads(res.stdout)
        self.assertTrue(data["global_files"]["GEMINI.md"]["exists"])
        self.assertFalse(data["global_files"]["GEMINI.md"]["memsync"])
        self.assertFalse(data["global_files"]["local-installed-tools.md"]["exists"])
        self.assertIsInstance(data["detected_toolchains"], dict)
        self.assertTrue("python" in data["detected_toolchains"] or "python3" in data["detected_toolchains"])
        self.assertFalse(data["config_exists"])
        discovered = [Path(p).resolve() for p in data["discovered_agy_workspaces"]]
        self.assertIn(real_ws.resolve(), discovered)
        self.assertNotIn(sidecar_ws.resolve(), discovered)
        self.assertNotIn(swarm_ws.resolve(), discovered)

    def test_index_only_mode_and_mode_toggles(self) -> None:
        res = run_memsync(
            self.mem_home,
            "bootstrap",
            "--lang", "en",
            "--agents-cache", "off",
            "--schedule", "on",
            "--profile", "standard",
        )
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        cfg = json.loads((self.ops / "config.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["mode"]["agents_cache_enabled"])
        self.assertFalse(cfg["mode"]["schedule_enabled"])  # coerced off when agents_cache is off
        self.assertFalse((self.mem_home / "AGENTS.md").exists())

        # Cannot turn schedule on while agents_cache is off
        bad_cfg = run_memsync(self.mem_home, "config", "set", "--schedule", "on")
        self.assertEqual(bad_cfg.returncode, 2)

        # Workspace init in index-only mode creates GEMINI.md + memories, skips AGENTS.md
        ws = self.root / "demo-repo"
        ws.mkdir()
        (ws / ".git").mkdir()
        init_res = run_memsync(self.mem_home, "init", str(ws), "--summary", "Demo repo")
        self.assertEqual(init_res.returncode, 0, init_res.stdout)
        self.assertTrue((ws / "GEMINI.md").exists())
        self.assertFalse((ws / "AGENTS.md").exists())
        self.assertIn(".gemini/memories/", (ws / ".gitignore").read_text(encoding="utf-8"))

        # Lint passes cleanly without AGENTS.md warnings
        lint_res = run_memsync(self.mem_home, "lint")
        self.assertEqual(lint_res.returncode, 0, lint_res.stdout)
        self.assertIn("warns=0", lint_res.stdout)

        # sync-plan reports index-only skip cleanly
        plan_res = run_memsync(self.mem_home, "sync-plan")
        self.assertEqual(plan_res.returncode, 0)
        self.assertIn("mode=index-only", plan_res.stdout)

        # Switching agents_cache back on works
        on_res = run_memsync(self.mem_home, "config", "set", "--agents-cache", "on", "--schedule", "on")
        self.assertEqual(on_res.returncode, 0)
        cfg2 = json.loads((self.ops / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg2["mode"]["agents_cache_enabled"])
        self.assertTrue(cfg2["mode"]["schedule_enabled"])

    def test_foreign_agents_unmanaged_and_nested_guard(self) -> None:
        run_memsync(self.mem_home, "bootstrap", "--lang", "zh", "--agents-cache", "on")
        ws = self.root / "team-repo"
        ws.mkdir()
        foreign_agents_text = "# Team Handcrafted AGENTS\nDo not overwrite me.\n"
        (ws / "AGENTS.md").write_text(foreign_agents_text, encoding="utf-8")

        res = run_memsync(self.mem_home, "init", str(ws), "--no-manage-agents", "--summary", "Team repo")
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual((ws / "AGENTS.md").read_text(encoding="utf-8"), foreign_agents_text)

        lint_res = run_memsync(self.mem_home, "lint")
        self.assertEqual(lint_res.returncode, 0, lint_res.stdout)

        # Nested child directory should be rejected by default
        child = ws / "packages" / "sub"
        child.mkdir(parents=True)
        nested_res = run_memsync(self.mem_home, "init", str(child), "--summary", "Sub")
        self.assertEqual(nested_res.returncode, 2)

        # Ignored directories work and update global GEMINI.md
        tmp_ws = self.root / "scratch-dir"
        tmp_ws.mkdir()
        ign_res = run_memsync(self.mem_home, "ws", "ignore", str(tmp_ws), "--reason", "temp")
        self.assertEqual(ign_res.returncode, 0)
        self.assertIn(str(tmp_ws.resolve()), (self.mem_home / "GEMINI.md").read_text(encoding="utf-8"))

    def test_two_stage_diff_secret_guard_and_cross_tool_copy(self) -> None:
        codex_target = self.root / "external" / "codex" / "AGENTS.md"
        codex_target.parent.mkdir(parents=True)
        codex_target.write_text("# Old Codex\n", encoding="utf-8")

        run_memsync(
            self.mem_home,
            "bootstrap",
            "--lang", "en",
            "--agents-cache", "on",
            "--target", f"codex={codex_target}",
        )
        ws = self.root / "app1"
        ws.mkdir()
        run_memsync(self.mem_home, "init", str(ws), "--summary", "App one")

        # Add a sync:auto project memory and a sync:never global pointer memory
        ws_mem = ws / ".gemini" / "memories" / "api-design.md"
        ws_mem.write_text(
            "---\nname: api-design\ndescription: [2026-11-16 project] Initial API choice\n"
            "type: project\nscope: project\nupdated: 2026-11-16\n---\n\nUse REST v1.\n\n"
            "**Why:** Simple.\n**How to apply:** Keep endpoints under /api/v1.\n",
            encoding="utf-8",
        )
        ws_gemini = ws / "GEMINI.md"
        ws_gemini.write_text(
            ws_gemini.read_text(encoding="utf-8")
            + "- [2026-11-16 project·decision][API Design](.gemini/memories/api-design.md) - Use /api/v1\n",
            encoding="utf-8",
        )

        gl_secret_ptr = self.mem_home / "memories" / "key-pointer.md"
        gl_secret_ptr.write_text(
            "---\nname: key-pointer\ndescription: [2026-11-16 reference] Key pointer\n"
            "type: reference\nscope: global\nupdated: 2026-11-16\nsync: never\n---\n\n"
            "Secret stored at ~/.env.secret (never sk-abcdefghijklmnopqrstuvwxyz1234).\n",
            encoding="utf-8",
        )
        gl_gemini = self.mem_home / "GEMINI.md"
        gl_gemini.write_text(
            gl_gemini.read_text(encoding="utf-8")
            + "- [2026-11-16 reference·pointer][Key Pointer](memories/key-pointer.md) - ~/.env.secret pointer\n",
            encoding="utf-8",
        )

        # sync-plan detects workspace NEW + redacts sync:never body
        plan_res = run_memsync(self.mem_home, "sync-plan")
        self.assertEqual(plan_res.returncode, 0, plan_res.stdout)
        self.assertIn("ws_update=app1 global_update=yes", plan_res.stdout)

        # apply refuses leaked secret in draft
        bad_draft = self.ops / "work" / "bad-ws-draft.md"
        bad_draft.write_text(
            "# AGENTS.md\n> Auto-generated snapshot. Do not edit manually. GEMINI.md\n"
            "## 1. Active\napi_key=sk-1234567890abcdef12345678\n## 2. Pitfalls\nNone\n",
            encoding="utf-8",
        )
        bad_apply = run_memsync(self.mem_home, "apply", "--scope", "app1", str(bad_draft))
        self.assertEqual(bad_apply.returncode, 1)

        # Clean apply for Stage 1 workspace
        good_ws_draft = self.ops / "work" / "good-ws-draft.md"
        good_ws_draft.write_text(
            f"# AGENTS.md (app1)\n> Auto-generated snapshot. Do not edit manually. [{ws / 'GEMINI.md'}]({ws / 'GEMINI.md'})\n\n"
            "## 1. Active Project Progress & Decisions\n\n- Endpoints under `/api/v1`.\n\n"
            "## 2. Project-Specific Conventions & Pitfalls\n\n- Keep REST v1.\n",
            encoding="utf-8",
        )
        ok_ws = run_memsync(self.mem_home, "apply", "--scope", "app1", str(good_ws_draft))
        self.assertEqual(ok_ws.returncode, 0, ok_ws.stdout)

        # Stage 2 global-input must redact sync:never body
        gi_res = run_memsync(self.mem_home, "global-input")
        self.assertEqual(gi_res.returncode, 0, gi_res.stdout)
        gi_reports = list((self.ops / "work").glob("sync-global-*.md"))
        self.assertEqual(len(gi_reports), 1)
        gi_text = gi_reports[0].read_text(encoding="utf-8")
        self.assertIn("sync:never redacted", gi_text)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz1234", gi_text)

        # Apply global snapshot -> also copies to Codex target with backup
        good_gl_draft = self.ops / "work" / "good-gl-draft.md"
        good_gl_draft.write_text(
            f"# AGENTS.md\n> Auto-generated snapshot. Do not edit manually. [{gl_gemini}]({gl_gemini})\n\n"
            "## 1. User Profile\n- Clean.\n\n"
            "## 2. Workspaces\n- app1 active.\n\n"
            "## 3. Conventions\n- Tests first.\n\n"
            "## 4. Environment\n- Key pointer in memories/key-pointer.md.\n",
            encoding="utf-8",
        )
        ok_gl = run_memsync(self.mem_home, "apply", "--scope", "global", str(good_gl_draft))
        self.assertEqual(ok_gl.returncode, 0, ok_gl.stdout)
        self.assertEqual(codex_target.read_text(encoding="utf-8").strip(), good_gl_draft.read_text(encoding="utf-8").strip())
        self.assertTrue(any((self.ops / "backup").glob("copy-codex-*.md")))

        # Immediate follow-up sync-plan must report 0 changes
        plan2 = run_memsync(self.mem_home, "sync-plan")
        self.assertEqual(plan2.returncode, 0)
        self.assertIn("ws_update=none global_update=no", plan2.stdout)

        # Modify then verify [MODIFIED] unified diff, and delete then verify [DELETED]
        ws_mem.write_text(
            "---\nname: api-design\ndescription: [2026-11-16 project] Updated API choice\n"
            "type: project\nscope: project\nupdated: 2026-11-16\n---\n\nUse REST v2.\n\n"
            "**Why:** Versioning.\n**How to apply:** Keep endpoints under /api/v2.\n",
            encoding="utf-8",
        )
        plan3 = run_memsync(self.mem_home, "sync-plan")
        self.assertEqual(plan3.returncode, 0)
        self.assertIn("ws_update=app1 global_update=yes", plan3.stdout)
        ws_rep = list((self.ops / "work").glob("sync-ws-app1-*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("[MODIFIED] api-design.md", ws_rep)
        self.assertIn("-Use REST v1.", ws_rep)
        self.assertIn("+Use REST v2.", ws_rep)

        ws_mem.unlink()
        plan4 = run_memsync(self.mem_home, "sync-plan")
        self.assertEqual(plan4.returncode, 0)
        ws_rep2 = list((self.ops / "work").glob("sync-ws-app1-*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("[DELETED]", ws_rep2)
        self.assertIn("api-design.md", ws_rep2)

    def test_budget_profiles_standard_vs_extended(self) -> None:
        run_memsync(self.mem_home, "bootstrap", "--lang", "en", "--agents-cache", "on", "--profile", "standard")
        gl_gemini = self.mem_home / "GEMINI.md"
        # Push global GEMINI.md past 24KB hard cap in standard profile
        gl_gemini.write_text(
            gl_gemini.read_text(encoding="utf-8") + ("<!-- filler -->\n" * 1700),
            encoding="utf-8",
        )
        res_std = run_memsync(self.mem_home, "lint")
        self.assertEqual(res_std.returncode, 1)

        # Switching to extended profile raises cap and passes
        run_memsync(self.mem_home, "config", "set", "--profile", "extended")
        res_ext = run_memsync(self.mem_home, "lint")
        self.assertEqual(res_ext.returncode, 0, res_ext.stdout)

    def test_legacy_workspaces_json_compatibility(self) -> None:
        self.ops.mkdir(parents=True, exist_ok=True)
        ws = self.root / "legacy-ws"
        ws.mkdir()
        (ws / "GEMINI.md").write_text("# Legacy WS\n\n## 项目索引\n", encoding="utf-8")
        (ws / "AGENTS.md").write_text("# AGENTS\n> 自动生成\nGEMINI.md\n", encoding="utf-8")
        (self.mem_home / "GEMINI.md").write_text("# Global\n\n## 已注册工作区\n- `legacy-ws` (`" + str(ws) + "`): demo\n\n## 全局索引\n", encoding="utf-8")
        (self.mem_home / "AGENTS.md").write_text("# Global AGENTS\n> 自动生成\nGEMINI.md\n", encoding="utf-8")
        (self.ops / "workspaces.json").write_text(
            json.dumps({
                "version": 1,
                "auto_copy_on_global_apply": False,
                "copy_targets": {"claude": str(self.root / "claude" / "CLAUDE.md")},
                "workspaces": [{"name": "legacy-ws", "path": str(ws), "summary": "demo", "enabled": True}],
                "ignored": [],
            }),
            encoding="utf-8",
        )
        res = run_memsync(self.mem_home, "lint")
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_shipped_milkfrog_demo_vaults_pass_lint(self) -> None:
        for lang in ("zh", "en"):
            with self.subTest(lang=lang):
                sandbox = self.root / f"demo_{lang}"
                gem = sandbox / ".gemini"
                ops = gem / "memory-ops"
                src_global = EXAMPLES_DIR / lang / "global"
                src_ws = EXAMPLES_DIR / lang / "milkfrog-blog"
                dst_ws = sandbox / "milkfrog-blog"

                shutil.copytree(src_global, gem)
                shutil.copytree(src_ws, dst_ws)
                ops.mkdir(parents=True, exist_ok=True)
                (ops / "config.json").write_text(
                    json.dumps({
                        "version": 2,
                        "lang": lang,
                        "mode": {"agents_cache_enabled": True, "schedule_enabled": False, "auto_discover_unregistered": False},
                        "limits": {"profile": "standard"},
                        "workspaces": [{"name": "milkfrog-blog", "path": str(dst_ws), "summary": "demo", "enabled": True}],
                        "ignored": [],
                    }),
                    encoding="utf-8",
                )
                res = run_memsync(gem, "lint")
                self.assertEqual(res.returncode, 0, res.stdout)
                self.assertIn("errors=0 warns=0", res.stdout, f"demo {lang} had warnings: {res.stdout}")

    def test_templates_fit_standard_header_budget(self) -> None:
        for tpl in (
            TEMPLATES_DIR / "zh" / "global-gemini.full.md",
            TEMPLATES_DIR / "zh" / "global-gemini.index-only.md",
            TEMPLATES_DIR / "en" / "global-gemini.full.md",
            TEMPLATES_DIR / "en" / "global-gemini.index-only.md",
        ):
            head_bytes = len(tpl.read_bytes())
            self.assertLessEqual(head_bytes, 6_000, f"{tpl.name} exceeds 6KB standard header warn threshold ({head_bytes}B)")

    def test_local_installed_tools_conditional_pointer_check(self) -> None:
        run_memsync(self.mem_home, "bootstrap", "--lang", "en", "--agents-cache", "on")
        gl_gemini = self.mem_home / "GEMINI.md"
        draft = self.ops / "work" / "gl-draft.md"

        # Without local-installed-tools.md, omitting it produces 0 warnings
        today_str = str(dt.date.today())
        draft.write_text(
            f"# AGENTS.md\n> Auto-generated snapshot. Do not edit manually. Last synced: {today_str}. [{gl_gemini}]({gl_gemini})\n\n"
            "## 1. User\n- None\n\n## 2. Workspaces\n- None\n\n## 3. Conventions\n- None\n\n## 4. Tools\n- None\n",
            encoding="utf-8",
        )
        res_clean = run_memsync(self.mem_home, "apply", "--scope", "global", str(draft))
        self.assertEqual(res_clean.returncode, 0, res_clean.stdout)
        self.assertIn("warns=0", res_clean.stdout)

        # Once local-installed-tools.md exists, omitting pointer warns cleanly
        tools_file = self.mem_home / "memories" / "local-installed-tools.md"
        tools_file.write_text(
            "---\nname: local-installed-tools\ndescription: [2026-11-17 reference] Tools\n"
            "type: reference\nscope: global\nupdated: 2026-11-17\nsync: auto\n---\n\n- Python 3\n",
            encoding="utf-8",
        )
        res_warn = run_memsync(self.mem_home, "apply", "--scope", "global", str(draft))
        self.assertEqual(res_warn.returncode, 0, res_warn.stdout)
        self.assertIn("warns=1", res_warn.stdout)

        # Adding pointer clears the warning
        draft.write_text(
            draft.read_text(encoding="utf-8") + "- Full registry: memories/local-installed-tools.md\n",
            encoding="utf-8",
        )
        res_ok = run_memsync(self.mem_home, "apply", "--scope", "global", str(draft))
        self.assertEqual(res_ok.returncode, 0, res_ok.stdout)
        self.assertIn("warns=0", res_ok.stdout)

    def test_no_private_data_or_uv_leaks_in_repo(self) -> None:
        forbidden = [
            "31185",
            "D:\\study",
            "ModelGate",
            "SignalTrace",
            "MyToDo",
            "jovanzhang6",
            "124.222.119.14",
            "LeapFrog",
            "xwechat_files",
            "openscreen-data",
            "Easton Jiang",
            "6724478416",
            "milkfrog.top",
        ]
        for path in SKILL_ROOT.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.name == "test_memsync.py":
                continue
            txt = path.read_text(encoding="utf-8", errors="ignore")
            for term in forbidden:
                self.assertNotIn(term, txt, f"Found private/forbidden string '{term}' in {path}")
            # Also check no 'uv run' left inside operational scripts/templates
            if path.suffix in (".py", ".json") or "templates" in path.parts or "SKILL" in path.name:
                self.assertNotIn("uv run", txt, f"Found 'uv run' dependency in {path}")

    def test_context_hook_install_modes_and_pb_parsing(self) -> None:
        # Install via bootstrap --context-hook on (omitting --hook-mode verifies default threshold mode)
        boot = run_memsync(
            self.mem_home,
            "bootstrap",
            "--lang", "zh",
            "--agents-cache", "off",
            "--context-hook", "on",
            "--hook-warn", "80",
        )
        self.assertEqual(boot.returncode, 0, boot.stdout + boot.stderr)
        self.assertIn("context_hook=installed", boot.stdout)
        cfg_boot = json.loads((self.ops / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg_boot["context_hook"]["mode"], "threshold")
        self.assertEqual(cfg_boot["context_hook"]["cooldown_calls"], 3)
        self.assertEqual(cfg_boot["context_hook"]["critical_percent"], 92)

        installed_script = self.ops / "context_hook.py"
        plugin_dir = self.mem_home / "config" / "plugins" / "milkfrog-context-hook"
        self.assertTrue(installed_script.is_file())
        self.assertTrue((plugin_dir / "plugin.json").is_file())
        hooks_data = json.loads((plugin_dir / "hooks.json").read_text(encoding="utf-8"))
        cmd = hooks_data["milkfrog-context-monitor"]["PreInvocation"][0]["command"]
        if platform.system() == "Windows":
            self.assertTrue(cmd.startswith("call "))
        self.assertIn(str(installed_script.resolve()), cmd)

        # doctor reports context_hook_installed=True
        doc = json.loads(run_memsync(self.mem_home, "doctor", "--json").stdout)
        self.assertTrue(doc["context_hook_installed"])
        self.assertTrue(doc["context_hook_script_exists"])

        # Prepare synthetic conversation SQLite DB (10% occupancy) + transcript fallback
        cid = "conv-test-01"
        db_dir = self.mem_home / "antigravity" / "conversations"
        db_dir.mkdir(parents=True)
        db_path = db_dir / f"{cid}.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB)")
        conn.execute("INSERT INTO gen_metadata VALUES (0, ?)", (make_gen_blob(3400, 70000, 734000),))
        conn.commit()
        conn.close()

        def call_hook(stdin_obj: dict[str, object]) -> dict[str, object]:
            env = os.environ.copy()
            env["MILKFROG_MEMORY_HOME"] = str(self.mem_home)
            res = subprocess.run(
                [sys.executable, str(installed_script)],
                input=json.dumps(stdin_obj).encode("utf-8"),
                env=env,
                capture_output=True,
                check=True,
            )
            return json.loads(res.stdout.decode("utf-8"))

        # Default threshold mode stays silent below 80%
        self.assertEqual(call_hook({"conversationId": cid, "lastUserInput": "中文输入测试"}), {})

        # Explicit always mode below 80% injects compact usage line without metadata
        run_memsync(self.mem_home, "config", "set", "--hook-mode", "always")
        low_out = call_hook({"conversationId": cid, "lastUserInput": "中文输入测试"})
        low_sys = low_out["injectSteps"][0]["systemMessage"]
        self.assertNotIn("metadata", low_sys)
        msg_low = low_sys["systemMessage"]
        self.assertIn("[上下文]", msg_low)
        self.assertIn("73.4K / 734.0K (10.0%)", msg_low)

        # Switch back to threshold mode -> silent below 80%, alerts at >= 80%
        run_memsync(self.mem_home, "config", "set", "--hook-mode", "threshold", "--hook-warn", "80")
        self.assertEqual(call_hook({"conversationId": cid}), {})

        # bump DB above 80% -> threshold mode triggers Chinese rescue alert
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO gen_metadata VALUES (1, ?)", (make_gen_blob(5000, 595000, 734000),))
        conn.commit()
        conn.close()
        high_out = call_hook({"conversationId": cid})
        high_sys = high_out["injectSteps"][0]["systemMessage"]
        self.assertNotIn("metadata", high_sys)
        msg_high = high_sys["systemMessage"]
        self.assertIn("上下文预警", msg_high)
        self.assertIn("81.7%", msg_high)
        self.assertIn("如果没有请忽略本消息", msg_high)

        # Standalone script without config.json also defaults to threshold (alerts at >= 80%)
        cfg_file = self.ops / "config.json"
        saved_cfg = cfg_file.read_text(encoding="utf-8")
        cfg_file.unlink()
        self.assertIn("上下文预警", call_hook({"conversationId": cid})["injectSteps"][0]["systemMessage"]["systemMessage"])
        cfg_file.write_text(saved_cfg, encoding="utf-8")

        # Cooldown (every 3 PLANNER_RESPONSE calls) + >=92% single critical bypass across large chunks
        tp1 = self.mem_home / "antigravity" / "brain" / cid / ".system_generated" / "logs" / "transcript.jsonl"
        tp1.parent.mkdir(parents=True, exist_ok=True)
        filler_generic = json.dumps({"type": "GENERIC", "content": "x" * 310_000})

        def write_tp(lines: list[dict[str, object]], pad_large: bool = False) -> None:
            rows = [json.dumps(x, ensure_ascii=False) for x in lines]
            if pad_large:
                rows.insert(-1, filler_generic)
            tp1.write_text("\n".join(rows) + "\n", encoding="utf-8")

        alert_81 = {"source": "SYSTEM_SDK", "type": "SYSTEM_MESSAGE", "content": msg_high}
        planner_step = {"type": "PLANNER_RESPONSE", "input_tokens": 5000, "cache_read_tokens": 595000}

        # 1 and 2 PLANNER_RESPONSE calls after 81.7% alert stay throttled (even across >300KB filler)
        write_tp([alert_81, planner_step], pad_large=True)
        self.assertEqual(call_hook({"conversationId": cid, "transcriptPath": str(tp1)}), {})
        write_tp([alert_81, planner_step, planner_step])
        self.assertEqual(call_hook({"conversationId": cid, "transcriptPath": str(tp1)}), {})

        # In always mode while throttled, high-water falls back to compact status rather than repeating full alert
        run_memsync(self.mem_home, "config", "set", "--hook-mode", "always")
        always_throttled = call_hook({"conversationId": cid, "transcriptPath": str(tp1)})["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("[上下文]", always_throttled)
        self.assertNotIn("上下文预警", always_throttled)
        run_memsync(self.mem_home, "config", "set", "--hook-mode", "threshold")

        # Reaching 3 PLANNER_RESPONSE calls after alert fires again
        write_tp([alert_81, planner_step, planner_step, planner_step])
        self.assertIn("上下文预警", call_hook({"conversationId": cid, "transcriptPath": str(tp1)})["injectSteps"][0]["systemMessage"]["systemMessage"])

        # During cooldown (1 call after 81.7%), jumping to >=92% triggers ONE critical bypass
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO gen_metadata VALUES (2, ?)", (make_gen_blob(5000, 678000, 734000),))
        conn.commit()
        conn.close()
        write_tp([alert_81, planner_step])
        crit_msg = call_hook({"conversationId": cid, "transcriptPath": str(tp1)})["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("93.1%", crit_msg)
        self.assertIn("如果没有请忽略本消息", crit_msg)

        # Next call at 93.1%+ within cooldown (after critical alert already fired) is throttled again
        alert_93 = {"source": "SYSTEM_SDK", "type": "SYSTEM_MESSAGE", "content": crit_msg}
        write_tp([alert_93, planner_step])
        self.assertEqual(call_hook({"conversationId": cid, "transcriptPath": str(tp1)}), {})

        # Verify cooldown/critical flags via config set and hook status, plus English alert wording
        run_memsync(self.mem_home, "config", "set", "--lang", "en", "--hook-cooldown", "5", "--hook-critical", "95")
        hk_stat = run_memsync(self.mem_home, "hook", "status")
        self.assertIn("cooldown_calls=5", hk_stat.stdout)
        self.assertIn("critical_percent=95", hk_stat.stdout)
        write_tp([alert_93, planner_step, planner_step, planner_step, planner_step])
        self.assertEqual(call_hook({"conversationId": cid}), {})
        write_tp([alert_93, planner_step, planner_step, planner_step, planner_step, planner_step])
        en_high = call_hook({"conversationId": cid})["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertIn("[Context Alert", en_high)
        self.assertIn("if none, ignore this message.", en_high)

        # switch language to English + verify transcript fallback when DB missing
        run_memsync(self.mem_home, "config", "set", "--lang", "en", "--hook-mode", "always")
        tpath = self.mem_home / "antigravity" / "brain" / "other-cid" / ".system_generated" / "logs" / "transcript.jsonl"
        tpath.parent.mkdir(parents=True)
        tpath.write_text(
            json.dumps({"type": "PLANNER_RESPONSE", "input_tokens": 1200, "cache_read_tokens": 3800}) + "\n",
            encoding="utf-8",
        )
        fb_out = call_hook({"conversationId": "other-cid", "transcriptPath": str(tpath)})
        self.assertIn("[Context] 5.0K / ? (?%)", fb_out["injectSteps"][0]["systemMessage"]["systemMessage"])

        # uninstall cleans plugin dir and disables flag
        un = run_memsync(self.mem_home, "hook", "uninstall")
        self.assertEqual(un.returncode, 0, un.stdout)
        self.assertFalse(plugin_dir.exists())
        cfg_after = json.loads((self.ops / "config.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg_after["context_hook"]["enabled"])

    def test_schedule_templates_require_change_summary_report(self) -> None:
        sidecar = json.loads((TEMPLATES_DIR / "shared" / "sidecar-schedule.json").read_text(encoding="utf-8"))
        prompt = sidecar["args"][-1]
        self.assertIn("trigger files", prompt)
        self.assertIn("summarizing what changed", prompt)
        self.assertIn("memsync.py show/search", prompt)
        self.assertIn("replaced", prompt)

        zh_runbook = (TEMPLATES_DIR / "zh" / "runbook.md").read_text(encoding="utf-8")
        en_runbook = (TEMPLATES_DIR / "en" / "runbook.md").read_text(encoding="utf-8")
        self.assertIn("## 本次改动摘要", zh_runbook)
        self.assertIn("触发源", zh_runbook)
        self.assertIn("memsync show", zh_runbook)
        self.assertIn("memsync search", zh_runbook)
        self.assertIn("严禁把并列增删脑补成替代关系", zh_runbook)
        self.assertIn("## What Changed", en_runbook)
        self.assertIn("sources:", en_runbook)
        self.assertIn("memsync show", en_runbook)
        self.assertIn("memsync search", en_runbook)
        self.assertIn("Never invent replacement relationships", en_runbook)

    def test_readonly_show_search_redaction_and_traversal_guard(self) -> None:
        run_memsync(self.mem_home, "bootstrap", "--lang", "en", "--agents-cache", "on")
        ws = self.root / "alpha-ws"
        ws.mkdir()
        run_memsync(self.mem_home, "init", str(ws), "--summary", "Alpha workspace")

        # Write a normal workspace memory and a sync:never global memory
        ws_mem = ws / ".gemini" / "memories" / "release-rule.md"
        policy_pad = "\n".join(f"- Stable checklist item {i}" for i in range(1, 7))
        ws_mem.write_text(
            "---\nname: release-rule\ndescription: [2026-11-20 feedback] Release gate\n"
            "type: feedback\nscope: project\nupdated: 2026-11-20\n---\n\n"
            f"## Tagging Policy\n{policy_pad}\n- Always run unit tests before tagging alpha-release-v1.\n",
            encoding="utf-8",
        )
        secret_mem = self.mem_home / "memories" / "vault-pointer.md"
        secret_mem.write_text(
            "---\nname: vault-pointer\ndescription: [2026-11-20 reference] Vault pointer location\n"
            "type: reference\nscope: global\nupdated: 2026-11-20\nsync: never\n---\n\n"
            "Hidden body marker: top-secret-token-xyz987.\n",
            encoding="utf-8",
        )

        # Apply once so sync-state caches the before version of release-rule.md
        today_str = str(dt.date.today())
        ws_draft = self.ops / "work" / "ws-draft.md"
        ws_draft.write_text(
            f"# AGENTS.md (alpha-ws)\n> Auto-generated snapshot. Last synced: {today_str}. GEMINI.md\n\n"
            "## 1. Active\n- Active.\n\n## 2. Pitfalls\n- Run tests.\n",
            encoding="utf-8",
        )
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "alpha-ws", str(ws_draft)).returncode, 0)

        # Update then delete release-rule.md to test --version both and --version before
        ws_mem.write_text(
            "---\nname: release-rule\ndescription: [2026-11-23 feedback] Release gate v2\n"
            "type: feedback\nscope: project\nupdated: 2026-11-23\n---\n\n"
            f"## Tagging Policy\n{policy_pad}\n- Always run unit tests before tagging alpha-release-v2.\n",
            encoding="utf-8",
        )
        both_res = run_memsync(self.mem_home, "show", "alpha-ws", "release-rule.md", "--version", "both", "--stdout")
        self.assertEqual(both_res.returncode, 0, both_res.stderr)
        self.assertIn("alpha-release-v1", both_res.stdout)
        self.assertIn("alpha-release-v2", both_res.stdout)
        self.assertIn("[section: ## Tagging Policy]", both_res.stdout)

        # Path traversal must be rejected
        bad_show = run_memsync(self.mem_home, "show", "alpha-ws", "../AGENTS.md")
        self.assertEqual(bad_show.returncode, 2)

        # sync:never entry must be strictly redacted in show AND search
        sec_show = run_memsync(self.mem_home, "show", "global", "vault-pointer.md", "--stdout")
        self.assertEqual(sec_show.returncode, 0)
        self.assertIn("[REDACTED: sync: never]", sec_show.stdout)
        self.assertNotIn("top-secret-token-xyz987", sec_show.stdout)

        sec_search_body = run_memsync(self.mem_home, "search", "top-secret-token-xyz987", "--stdout")
        self.assertEqual(sec_search_body.returncode, 0)
        self.assertIn("(no matches found)", sec_search_body.stdout)

        sec_search_meta = run_memsync(self.mem_home, "search", "Vault pointer location", "--stdout")
        self.assertEqual(sec_search_meta.returncode, 0)
        self.assertIn("CURRENT/sync:never-meta-only", sec_search_meta.stdout)
        self.assertNotIn("top-secret-token-xyz987", sec_search_meta.stdout)

        # Delete release-rule.md -> show --version before & search both still locate cached pre-delete body
        ws_mem.unlink()
        del_show = run_memsync(self.mem_home, "show", "alpha-ws", "release-rule", "--version", "before", "--stdout")
        self.assertEqual(del_show.returncode, 0)
        self.assertIn("alpha-release-v1", del_show.stdout)

        del_search = run_memsync(self.mem_home, "search", "alpha-release-v1", "--stdout")
        self.assertEqual(del_search.returncode, 0)
        self.assertIn("DELETED-BEFORE", del_search.stdout)
        self.assertIn("## Tagging Policy", del_search.stdout)

        # Default report mode writes ASCII summary + report file inside work/
        rep_show = run_memsync(self.mem_home, "show", "alpha-ws", "AGENTS.md")
        self.assertEqual(rep_show.returncode, 0)
        self.assertIn("show: scope=alpha-ws target=AGENTS.md", rep_show.stdout)
        self.assertTrue(any((self.ops / "work").glob("show-alpha-ws-AGENTS-*.md")))

    def test_enhanced_diff_inline_hints_and_global_input_slimming(self) -> None:
        run_memsync(self.mem_home, "bootstrap", "--lang", "en", "--agents-cache", "on")
        ws_active = self.root / "ws-active"
        ws_idle = self.root / "ws-idle"
        ws_active.mkdir()
        ws_idle.mkdir()
        run_memsync(self.mem_home, "init", str(ws_active), "--summary", "Active repo")
        run_memsync(self.mem_home, "init", str(ws_idle), "--summary", "Idle repo")

        # Seed a global memory with a long comma-separated inventory line below a section heading
        inv_pad = "\n".join(f"- Core runtime tool {i}: installed and verified." for i in range(1, 7))
        tools_mem = self.mem_home / "memories" / "tool-list.md"
        tools_mem.write_text(
            "---\nname: tool-list\ndescription: [2026-11-20 reference] Installed skills list\n"
            "type: reference\nscope: global\nupdated: 2026-11-20\n---\n\n"
            f"## Skill Inventory\n{inv_pad}\n"
            "- **Installed skills directory**: `~/.agents/skills/` (total `12` items: `alpha-kit`, `beta-kit`, "
            "`gamma-kit`, `delta-kit`, `epsilon-kit`, `zeta-kit`, `old-video-tool`, `omega-kit`, and shared helpers).\n",
            encoding="utf-8",
        )

        # Apply initial Stage-1 and Stage-2 snapshots (ws_active > 4 KB so Stage-2 diff slimming triggers)
        today_str = str(dt.date.today())
        filler = "\n".join(f"- Stable milestone item {i:03d}: verified baseline detail line." for i in range(85))
        active_v1 = (
            f"# AGENTS.md (ws-active)\n> Auto-generated snapshot. Last synced: {today_str}. GEMINI.md\n\n"
            f"## 1. Active Project Progress\n{filler}\n- Current status: v1 baseline.\n\n"
            "## 2. Project-Specific Conventions\n- Keep deterministic builds.\n"
        )
        idle_v1 = (
            f"# AGENTS.md (ws-idle)\n> Auto-generated snapshot. Last synced: {today_str}. GEMINI.md\n\n"
            "## 1. Active Project Progress\n- UNIQUE_IDLE_MARKER_SHOULD_NOT_REPEAT.\n\n"
            "## 2. Project-Specific Conventions\n- None.\n"
        )
        d1 = self.ops / "work" / "d-active1.md"
        d2 = self.ops / "work" / "d-idle1.md"
        d3 = self.ops / "work" / "d-gl1.md"
        d1.write_text(active_v1, encoding="utf-8")
        d2.write_text(idle_v1, encoding="utf-8")
        d3.write_text(
            f"# AGENTS.md\n> Auto-generated snapshot. Last synced: {today_str}. GEMINI.md\n\n"
            "## 1. User\n- None\n\n## 2. Workspaces\n- ws-active / ws-idle\n\n"
            "## 3. Conventions\n- None\n\n## 4. Tools\n- See tool-list.md\n",
            encoding="utf-8",
        )
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "ws-active", str(d1)).returncode, 0)
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "ws-idle", str(d2)).returncode, 0)
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "global", str(d3)).returncode, 0)

        # Now update ws-active (only 1 line) and edit tool-list.md (remove old-video-tool, add new-audio-tool)
        active_v2 = active_v1.replace("Current status: v1 baseline.", "Current status: v2 shipped.")
        d1.write_text(active_v2, encoding="utf-8")
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "ws-active", str(d1)).returncode, 0)

        tools_mem.write_text(
            "---\nname: tool-list\ndescription: [2026-11-23 reference] Installed skills list\n"
            "type: reference\nscope: global\nupdated: 2026-11-23\n---\n\n"
            f"## Skill Inventory\n{inv_pad}\n"
            "- **Installed skills directory**: `~/.agents/skills/` (total `12` items: `alpha-kit`, `beta-kit`, "
            "`gamma-kit`, `delta-kit`, `epsilon-kit`, `new-audio-tool`, `zeta-kit`, `omega-kit`, and shared helpers).\n",
            encoding="utf-8",
        )

        gi_res = run_memsync(self.mem_home, "global-input")
        self.assertEqual(gi_res.returncode, 0, gi_res.stdout)
        gi_text = list((self.ops / "work").glob("sync-global-*.md"))[0].read_text(encoding="utf-8")

        # Idle workspace must be collapsed without dumping its body
        self.assertIn("### [UNCHANGED] Workspace `ws-idle`", gi_text)
        self.assertNotIn("UNIQUE_IDLE_MARKER_SHOULD_NOT_REPEAT", gi_text)
        # Active large workspace (>4 KB) should emit incremental diff, not full 85 filler lines
        self.assertIn("### [UPDATED] Workspace `ws-active`", gi_text)
        self.assertIn("+- Current status: v2 shipped.", gi_text)
        self.assertNotIn("Stable milestone item 010", gi_text)
        # Modified global memory should have inline delta hint (without unchanged zeta-kit noise), section heading, and small-file fulltext
        self.assertIn("co-occurring delete+add does NOT imply replacement", gi_text)
        self.assertIn("removed [`old-video-tool`] | added [`new-audio-tool`]", gi_text)
        self.assertIn("[section: ## Skill Inventory]", gi_text)
        self.assertIn("Updated Full Body", gi_text)

        # Disabling ws-idle surfaces [REMOVED/DISABLED] notice in global-input
        self.assertEqual(run_memsync(self.mem_home, "ws", "disable", "ws-idle").returncode, 0)
        self.assertEqual(run_memsync(self.mem_home, "global-input").returncode, 0)
        gi_text2 = list((self.ops / "work").glob("sync-global-*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("### [REMOVED/DISABLED] Workspace `ws-idle`", gi_text2)

    def test_apply_guardrail_warnings_and_work_pruning(self) -> None:
        run_memsync(self.mem_home, "bootstrap", "--lang", "en", "--agents-cache", "on")
        ws = self.root / "guard-ws"
        ws.mkdir()
        run_memsync(self.mem_home, "init", str(ws), "--summary", "Guard repo")

        # Seed a memory and a >= 2 KB initial workspace AGENTS.md
        mem_del = ws / ".gemini" / "memories" / "obsolete-rule.md"
        mem_del.write_text(
            "---\nname: obsolete-rule\ndescription: [2026-11-20 feedback] Old rule\n"
            "type: feedback\nscope: project\nupdated: 2026-11-20\n---\n\nOld text.\n",
            encoding="utf-8",
        )
        today_str = str(dt.date.today())
        big_body = "\n".join(f"- Important active decision line number {i:03d} kept in cache." for i in range(45))
        big_draft = self.ops / "work" / "big-draft.md"
        big_draft.write_text(
            f"# AGENTS.md (guard-ws)\n> Auto-generated snapshot. Last synced: {today_str}. GEMINI.md\n\n"
            f"## 1. Active\n{big_body}\n\n## 2. Pitfalls\n- See obsolete-rule.md\n",
            encoding="utf-8",
        )
        r0 = run_memsync(self.mem_home, "apply", "--scope", "guard-ws", str(big_draft))
        self.assertEqual(r0.returncode, 0)
        self.assertIn("warns=0", r0.stdout)

        # Case 1: missing today's date warns cleanly; legitimate shrinkage no longer triggers noisy >30% warnings
        tiny_stale = self.ops / "work" / "tiny-stale.md"
        tiny_stale.write_text(
            "# AGENTS.md (guard-ws)\n> Auto-generated snapshot. Last synced: 2020-01-01. GEMINI.md\n\n"
            "## 1. Active\n- Short.\n\n## 2. Pitfalls\n- Short.\n",
            encoding="utf-8",
        )
        r_dry = run_memsync(self.mem_home, "apply", "--scope", "guard-ws", "--dry-run", str(tiny_stale))
        self.assertEqual(r_dry.returncode, 0)
        self.assertIn("warns=1", r_dry.stdout)
        rep_dry = list((self.ops / "work").glob("apply-guard-ws-*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("does not contain today's date", rep_dry)
        self.assertNotIn("shrank by >30%", rep_dry)

        # Case 2: delete obsolete-rule.md but leave filename in draft -> deleted-residue warning + work pruning
        mem_del.unlink()
        expired_work = self.ops / "work" / "lint-2020-01-01.md"
        keep_nondated = self.ops / "work" / "notes-keep.md"
        expired_work.write_text("old report\n", encoding="utf-8")
        keep_nondated.write_text("keep me\n", encoding="utf-8")

        r_del = run_memsync(self.mem_home, "apply", "--scope", "guard-ws", str(big_draft))
        self.assertEqual(r_del.returncode, 0)
        self.assertIn("warns=1", r_del.stdout)
        rep_del = list((self.ops / "work").glob("apply-guard-ws-*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("deleted memory 'obsolete-rule.md' still appears in draft", rep_del)
        self.assertFalse(expired_work.exists())
        self.assertTrue(keep_nondated.exists())

    def test_sync_mode_isolated_local_and_legacy_compat(self) -> None:
        run_memsync(self.mem_home, "bootstrap", "--lang", "zh", "--agents-cache", "on")
        iso_ws = self.root / "thesis-local"
        iso_ws.mkdir()
        init_res = run_memsync(
            self.mem_home, "init", str(iso_ws), "--sync-mode", "local", "--summary", "Isolated thesis workspace"
        )
        self.assertEqual(init_res.returncode, 0, init_res.stdout)
        self.assertIn("sync_mode=local", init_res.stdout)

        # Initial sync establishes global baseline with [ISOLATED] locator
        today_str = str(dt.date.today())
        gl_draft = self.ops / "work" / "gl-iso.md"
        gl_draft.write_text(
            f"# AGENTS.md\n> 由定时记忆同步自动生成。最近同步：{today_str}。GEMINI.md\n\n"
            "## 一、偏好\n- 无\n\n"
            "## 二、各工作区定位与当前动态\n- `thesis-local`：独立隔离工作区。\n\n"
            "## 三、规范\n- 无\n\n"
            "## 四、工具\n- 无\n",
            encoding="utf-8",
        )
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "global", str(gl_draft)).returncode, 0)

        # Adding local memory inside isolated workspace updates Stage 1 only, NEVER triggers Stage 2 global
        iso_mem = iso_ws / ".gemini" / "memories" / "private-note.md"
        iso_mem.write_text(
            "---\nname: private-note\ndescription: 【2026-11-28 项目】内部细节\n"
            "type: project\nscope: project\nupdated: 2026-11-28\n---\n\nPRIVATE_ISOLATED_BODY_MARKER.\n",
            encoding="utf-8",
        )
        (iso_ws / "GEMINI.md").write_text(
            (iso_ws / "GEMINI.md").read_text(encoding="utf-8")
            + "- 【2026-11-28 项目·草稿】[内部细节](.gemini/memories/private-note.md) — 仅本地\n",
            encoding="utf-8",
        )
        plan1 = run_memsync(self.mem_home, "sync-plan")
        self.assertEqual(plan1.returncode, 0, plan1.stdout)
        self.assertIn("ws_update=thesis-local", plan1.stdout)
        self.assertIn("global_update=no", plan1.stdout)
        self.assertIn("stage2_ws=no", plan1.stdout)

        # Apply Stage 1 locally -> global-input --part ws still emits [ISOLATED] with zero body leak
        ws_draft = self.ops / "work" / "iso-ws-draft.md"
        ws_draft.write_text(
            f"# AGENTS.md（thesis-local）\n> 自动生成。最近同步：{today_str}。GEMINI.md\n\n"
            "## 一、进展\n- PRIVATE_ISOLATED_BODY_MARKER\n\n## 二、规范\n- 无\n",
            encoding="utf-8",
        )
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "thesis-local", str(ws_draft)).returncode, 0)
        gi_ws = run_memsync(self.mem_home, "global-input", "--part", "ws")
        self.assertEqual(gi_ws.returncode, 0, gi_ws.stdout)
        gi_ws_text = list((self.ops / "work").glob("sync-global-ws-*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("[ISOLATED/UNCHANGED] Workspace `thesis-local`", gi_ws_text)
        self.assertNotIn("PRIVATE_ISOLATED_BODY_MARKER", gi_ws_text)

        # ws mode toggles cleanly between full / local / index / off
        self.assertEqual(run_memsync(self.mem_home, "ws", "mode", "thesis-local", "full").returncode, 0)
        self.assertIn("[sync_mode=full]", run_memsync(self.mem_home, "ws", "list").stdout)
        self.assertEqual(run_memsync(self.mem_home, "ws", "mode", "thesis-local", "off").returncode, 0)
        self.assertIn("[sync_mode=off]", run_memsync(self.mem_home, "ws", "list").stdout)

    def test_stage2_section_patch_and_split_state_machine(self) -> None:
        codex_target = self.root / "ext" / "codex-agents.md"
        codex_target.parent.mkdir(parents=True)
        run_memsync(
            self.mem_home,
            "bootstrap",
            "--lang", "en",
            "--agents-cache", "on",
            "--target", f"codex={codex_target}",
        )
        ws = self.root / "svc-a"
        ws.mkdir()
        run_memsync(self.mem_home, "init", str(ws), "--summary", "Service A")

        # Baseline Stage 1 + Stage 2
        old_date = "2026-11-01"
        ws_draft = self.ops / "work" / "svc-a.md"
        ws_draft.write_text(
            f"# AGENTS.md (svc-a)\n> Auto-generated snapshot. Last synced: {old_date}. GEMINI.md\n\n"
            "## 1. Active\n- v1\n\n## 2. Pitfalls\n- none\n",
            encoding="utf-8",
        )
        gl_init = self.ops / "work" / "gl-init.md"
        gl_init.write_text(
            f"# AGENTS.md (Global)\n> Auto-generated snapshot. Last synced: {old_date}. GEMINI.md\n\n"
            "## 1. User Profile & Core Preferences\n- KEEP_USER_VERBATIM\n\n"
            "## 2. Workspaces & Active Projects\n- svc-a: v1\n\n"
            "## 3. General Engineering Conventions\n- KEEP_RULES_VERBATIM\n\n"
            "## 4. Environment & Tooling Quick Reference\n- tool v1\n",
            encoding="utf-8",
        )
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "svc-a", str(ws_draft)).returncode, 0)
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "global", str(gl_init)).returncode, 0)

        # Now change BOTH workspace svc-a AND a global reference memory
        ws_draft.write_text(ws_draft.read_text(encoding="utf-8").replace("- v1", "- v2 shipped"), encoding="utf-8")
        self.assertEqual(run_memsync(self.mem_home, "apply", "--scope", "svc-a", str(ws_draft)).returncode, 0)
        gl_mem = self.mem_home / "memories" / "new-cli.md"
        gl_mem.write_text(
            "---\nname: new-cli\ndescription: [2026-11-28 reference] CLI tool v2\n"
            "type: reference\nscope: global\nupdated: 2026-11-28\n---\n\nInstalled tool v2.\n",
            encoding="utf-8",
        )
        plan = run_memsync(self.mem_home, "sync-plan")
        self.assertIn("stage2_ws=yes stage2_mem=yes", plan.stdout)

        # Stage 2A: global-input --part ws + apply --section 2 --no-copy
        self.assertEqual(run_memsync(self.mem_home, "global-input", "--part", "ws").returncode, 0)
        ws_patch = self.ops / "work" / "gl-sec2.md"
        ws_patch.write_text("## 2. Workspaces & Active Projects\n- svc-a: v2 shipped\n", encoding="utf-8")
        r2a = run_memsync(self.mem_home, "apply", "--scope", "global", "--section", "2", "--no-copy", str(ws_patch))
        self.assertEqual(r2a.returncode, 0, r2a.stdout)

        # After 2A: Section 2 updated, Sections 1/3/4 verbatim, date refreshed, AND stage2_mem STILL pending!
        mid_gl = (self.mem_home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(f"Last synced: {dt.date.today()}", mid_gl)
        self.assertIn("svc-a: v2 shipped", mid_gl)
        self.assertIn("KEEP_USER_VERBATIM", mid_gl)
        self.assertIn("KEEP_RULES_VERBATIM", mid_gl)
        self.assertIn("- tool v1", mid_gl)
        plan_mid = run_memsync(self.mem_home, "sync-plan")
        self.assertIn("stage2_ws=no stage2_mem=yes", plan_mid.stdout)

        # Stage 2B: global-input --part mem + apply --section 4 (updates Section 4, preserves Section 2, copies to codex)
        self.assertEqual(run_memsync(self.mem_home, "global-input", "--part", "mem").returncode, 0)
        mem_rep = list((self.ops / "work").glob("sync-global-mem-*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("suggested `--section 4`", mem_rep)
        mem_patch = self.ops / "work" / "gl-sec4.md"
        mem_patch.write_text("## 4. Environment & Tooling Quick Reference\n- tool v2\n", encoding="utf-8")
        r2b = run_memsync(self.mem_home, "apply", "--scope", "global", "--section", "4", str(mem_patch))
        self.assertEqual(r2b.returncode, 0, r2b.stdout)

        final_gl = (self.mem_home / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("svc-a: v2 shipped", final_gl)
        self.assertIn("- tool v2", final_gl)
        self.assertIn("KEEP_USER_VERBATIM", final_gl)
        self.assertEqual(codex_target.read_text(encoding="utf-8").strip(), final_gl.strip())
        self.assertIn("global_update=no stage2_ws=no stage2_mem=no", run_memsync(self.mem_home, "sync-plan").stdout)


if __name__ == "__main__":
    unittest.main()

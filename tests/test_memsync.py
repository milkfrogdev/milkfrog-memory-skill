from __future__ import annotations

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
        draft.write_text(
            f"# AGENTS.md\n> Auto-generated snapshot. Do not edit manually. [{gl_gemini}]({gl_gemini})\n\n"
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

        # Standalone script without config.json also defaults to threshold (alerts at >= 80%)
        cfg_file = self.ops / "config.json"
        saved_cfg = cfg_file.read_text(encoding="utf-8")
        cfg_file.unlink()
        self.assertIn("上下文预警", call_hook({"conversationId": cid})["injectSteps"][0]["systemMessage"]["systemMessage"])
        cfg_file.write_text(saved_cfg, encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()

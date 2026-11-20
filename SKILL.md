---
name: milkfrog-memory
description: >-
  Install, migrate, or customize the MilkFrog dual-layer local memory system
  (GEMINI.md index + optional AGENTS.md hot snapshot cache) for Antigravity IDE.
  Use when a user asks to install or set up this memory system, migrate existing
  GEMINI.md/AGENTS.md rules, switch between dual-layer and index-only modes,
  enable optional daily snapshot sync, or customize memsync.py.
  Note: Targets Antigravity IDE (with optional copy to Codex/Claude); Antigravity
  CLI (agy) is not adapted or supported. Once installed, daily memory operation
  runs purely from ~/.gemini/GEMINI.md without loading this skill.
---

# MilkFrog Memory System Installer & Runbook

Chinese version: [SKILL.zh-CN.md](./SKILL.zh-CN.md)

## Goal & Deliverables

Set up a local, privacy-preserving Markdown memory system on the user's machine with explicit mode flags, migrate any existing rules cleanly with backups, verify zero lint errors, and leave runtime rules self-contained inside `~/.gemini/GEMINI.md` so this skill is no longer required for daily use.

| Deliverable | Path | Purpose |
| --- | --- | --- |
| Operations CLI | `~/.gemini/memory-ops/memsync.py` | Stdlib-only lint, diff, apply, workspace & config tool |
| State & Flags | `~/.gemini/memory-ops/config.json` | Mode switches (`agents_cache`, `schedule`, `limits`, `workspaces`) |
| Architecture Ref | `~/.gemini/memory-ops/DESIGN.md` | Offline copy of `references/architecture*.md` for customization |
| Global Entrypoint | `~/.gemini/GEMINI.md` | Self-contained runtime rules, workspace list & global index |
| Global Memories | `~/.gemini/memories/*.md` | Single source of truth for global `user/feedback/project/reference` |
| Sync Runbook *(if cache on)* | `~/.gemini/memory-ops/RUNBOOK.md` | Instructions for on-demand or scheduled `AGENTS.md` updates |
| Global Snapshot *(if cache on)* | `~/.gemini/AGENTS.md` | Initial distilled cache (`>=1` apply pass if content exists) |
| Context Hook *(if hook on)* | `~/.gemini/memory-ops/context_hook.py` & `~/.gemini/config/plugins/milkfrog-context-hook/` | Optional `PreInvocation` hook injecting context occupancy & >=80% rescue alerts |
| Cron Sidecar *(if schedule on)* | `~/.gemini/config/sidecars/daily-agents-memory-sync/sidecar.json` | Optional Antigravity IDE automation definition (never force-enabled) |

**Done When**: `python3 ~/.gemini/memory-ops/memsync.py lint` (using the verified Python executable) exits with `errors=0`, existing files are preserved or migrated with backups, and runtime instructions live in `~/.gemini/GEMINI.md`.

---

## Host Compatibility Notice

- **Supported**: **Antigravity IDE** (rules discovery + optional scheduled sidecar), plus optional one-way `copy-global` export to Codex / Claude Code (`~/.codex/AGENTS.md`, `~/.claude/CLAUDE.md`) or manual sync on other Markdown-rule tools.
- **Not Supported**: **Antigravity CLI (`agy`)** has not been adapted or tested. If the user is running `agy` CLI, inform them up front and stop unless they want manual `memsync.py` file setup only.

---

## Steps

### Step 1 · Read-Only Environment Inspection (Inspect First, Ask Only What Applies)

Before touching any user config file:
1. Find a working Python `>= 3.9` executable (`python3`, `python`, or on Windows `py -3` — verify with `<cmd> ./scripts/memsync.py --help`; beware Windows Store `python3.exe` alias stubs).
2. Run a read-only inspection from the skill folder:
   ```bash
   <PYTHON_CMD> ./scripts/memsync.py doctor --json
   ```
3. Note:
   - OS & detected timezone (`timezone`)
   - Whether `~/.gemini/GEMINI.md`, `~/.gemini/AGENTS.md`, `memories/local-installed-tools.md`, or `<cwd>/GEMINI.md`, `<cwd>/AGENTS.md` already exist and whether they are `memsync`-managed
   - Detected external tools (`~/.codex`, `~/.claude`) and standard CLI toolchains on `PATH` (`detected_toolchains`: `python`, `node`, `pnpm`, `uv`, `git`, `java`, `mvn`, `cargo`, `go`, `docker` — zero private folder scans)
   - Match response and template language to the user (`templates/zh/` for Chinese, `templates/en/` for English).

### Step 2 · Ask Setup Preferences (`ask_question`)

Skip questions that do not apply (for example, do not ask about external sync if none were detected; do not ask about migration if no foreign files exist). Batch relevant choices cleanly:

1. **Architecture Mode**:
   - `(Recommended) Dual-Layer: GEMINI.md index + AGENTS.md hot snapshot cache` (`agents_cache_enabled=true`)
   - `Index-Only: GEMINI.md + memories/*.md only (skip AGENTS.md cache and cron completely)` (`agents_cache_enabled=false`)
2. **Scheduled Sync** *(only if Dual-Layer chosen)*:
   - `(Recommended) Enable Antigravity daily scheduled sync` (default `06:00` local timezone, customizable)
   - `Manual sync only (generate RUNBOOK.md, update AGENTS.md only when I ask)`
3. **Budget Profile**:
   - `(Recommended) Standard (16 KB warn / 24 KB hard cap — fits default Antigravity limits)`
   - `Extended (40 KB / 160 KB — only if you patched/expanded IDE limits)`
4. **Existing Global `GEMINI.md` / `AGENTS.md`** *(only if `doctor` found non-empty foreign files)*:
   - `(Recommended) Translate & split into the 4-type memory system (show Keep/Drop verdict first, back up originals)`
   - `Keep existing global rules section intact above the new index`
5. **Existing Current Workspace `GEMINI.md` / `AGENTS.md`** *(only if in a folder with non-empty foreign `AGENTS.md` or wanting onboarding)*:
   - `(Recommended) Translate & migrate rules into memories (show Keep/Drop verdict first)`
   - `Keep existing AGENTS.md unmanaged (manage_agents=false, add GEMINI.md index only)`
   - `Ignore this folder completely (ws ignore)`
6. **Initial Toolchain Quick-Reference (`memories/local-installed-tools.md`)** *(skip if already present or migrated)*:
   - `(Recommended) Pre-populate memories/local-installed-tools.md (sync: auto) from doctor's read-only PATH scan so future sessions know your installed SDKs immediately`
   - `Skip for now (create it later when installing software or fixing OS gotchas)`
7. **Optional Seed Examples** *(for fresh empty installs)*:
   - Ask whether to keep the vault clean or inspect `examples/milkfrog-demo/` first.
8. **Context Monitor Hook** *(optional `PreInvocation` hook to warn before compaction erases unwritten rules)*:
   - `(Recommended) Always inject compact status + rescue alert at >=80%` (`mode="always"`, `warn_percent=80`)
   - `Alert only at >=80% (stay silent below 80%)` (`mode="threshold"`, `warn_percent=80`)
   - `Skip context hook`
9. **Cross-Tool Export** *(only if Dual-Layer + `doctor` detected `~/.codex` or `~/.claude`)*:
   - Ask which detected tools should receive automatic one-way `AGENTS.md` copies after global updates.

### Step 3 · Handle Existing File Migration First (If Chosen)

If migrating existing global or workspace `GEMINI.md` / `AGENTS.md`:
1. Read the full existing file(s) without editing them yet.
2. Present a **Keep / Merge / Drop Verdict Table**:
   - **Keep**: exact target (`global` vs `project`, `type`, new or existing `slug`, reason).
   - **Drop**: obsolete boilerplate, duplicate directory trees, secrets, or stale notes + reason.
3. Wait for explicit user confirmation on the verdict table before creating entries.

### Step 4 · Install Files, Bootstrap State & Apply

1. Copy `./scripts/memsync.py` to `~/.gemini/memory-ops/memsync.py` (and `./scripts/context_hook.py` to `~/.gemini/memory-ops/context_hook.py` if enabling the context hook).
2. Copy the matching language `references/architecture*.md` to `~/.gemini/memory-ops/DESIGN.md` so secondary customization works without this skill.
3. Run `bootstrap` (use `--no-global-files` if writing from a full template right after; pass `--context-hook on --hook-mode <always|threshold> --hook-warn 80` if enabling the hook):
   ```bash
   <PYTHON_CMD> ~/.gemini/memory-ops/memsync.py bootstrap \
     --lang <zh|en> \
     --agents-cache <on|off> \
     --schedule <on|off> \
     --schedule-time <HH:MM> \
     --timezone <IANA_TZ> \
     --profile <standard|extended> \
     --context-hook <on|off> \
     --hook-mode <always|threshold> \
     --no-global-files
   ```
   Pass `--target name=path` for any opted-in external tools. When `--context-hook on` runs (or later via `<PYTHON_CMD> ~/.gemini/memory-ops/memsync.py hook install`), `memsync.py` automatically registers the `~/.gemini/config/plugins/milkfrog-context-hook/` `PreInvocation` plugin (`plugin.json` + `hooks.json` using the verified Python executable).
4. Render global `~/.gemini/GEMINI.md`:
   - Back up any existing `~/.gemini/GEMINI.md` to `~/.gemini/memory-ops/backup/` before writing.
   - Use `templates/<lang>/global-gemini.full.md` (Dual-Layer) or `templates/<lang>/global-gemini.index-only.md` (Index-Only), substituting `{{MEMORY_HOME}}`, `{{OPS_DIR}}`, `{{PYTHON_CMD}}`, `{{BUDGET_PROFILE}}`.
   - Write approved migrated global memories into `~/.gemini/memories/<slug>.md` and add matching single-line links under Global Index. If the user opted in to pre-populating `local-installed-tools.md`, write `~/.gemini/memories/local-installed-tools.md` (`type: reference`, `scope: global`, `sync: auto`) using verified `detected_toolchains` facts + any user-confirmed proxy/mirror notes (keeping any credential pointers separate in `sync: never` files), and index it.
5. If Dual-Layer mode:
   - Render `templates/<lang>/runbook.md` into `~/.gemini/memory-ops/RUNBOOK.md` (substituting placeholders).
   - Prepare `~/.gemini/AGENTS.md` (either run initial `sync-plan -> global-input -> draft -> apply --scope global` if global memories exist, or let `bootstrap` / template seed initial sections).
6. If initializing the active workspace (`<cwd>`):
   - Run `<PYTHON_CMD> ~/.gemini/memory-ops/memsync.py init "<cwd>" --summary "<summary>"` (adding `--no-manage-agents` if user chose unmanaged, or running `ws ignore "<cwd>"` if ignored).
   - Write approved migrated workspace memories into `<cwd>/.gemini/memories/<slug>.md` + `<cwd>/GEMINI.md` index.
   - If Dual-Layer and `manage_agents=true` and memories were migrated, run `sync-plan` -> draft -> `apply --scope <ws>` then `global-input` -> draft -> `apply --scope global`.
7. If `schedule_enabled=true`:
   - Render `templates/shared/sidecar-schedule.json` to `~/.gemini/config/sidecars/daily-agents-memory-sync/sidecar.json` (set `CRON_TZ`, minute/hour, exact verified `<PYTHON_CMD>`, `workspace_uris`, and `access_grants` per `automation` rules).
   - **Never modify `user_config.json` or enable the automation silently.** Tell the user the exact display name (**Daily Memory Snapshot Sync**), provide `[Open Automations Dashboard](sidecar://dashboard)`, and offer to test-run once interactively so permissions can be verified.

---

## Constraints

- **Self-Contained After Install**: Never leave runtime references requiring `milkfrog-memory` skill to operate day-to-day. Daily behavior must live completely in `~/.gemini/GEMINI.md`.
- **Backup Before Overwrite**: Never overwrite pre-existing `GEMINI.md`, `AGENTS.md`, or external targets without copying to `~/.gemini/memory-ops/backup/`.
- **Secret Hygiene**: Never place plain-text API keys, tokens, passwords, or private hosts into `GEMINI.md`, `AGENTS.md`, or `sync: auto` entries. Mark credential location pointers `sync: never`.
- **Gitignore Safety**: Every git repository initialized with project memory must ignore `.gemini/memories/`.
- **Cross-Platform Commands**: Use the verified Python command directly; never assume `uv` is installed.

---

## Templates & References

- Architecture & rationale: [architecture.md](./references/architecture.md) | [architecture.zh-CN.md](./references/architecture.zh-CN.md)
- Schema, flags & CLI: [schema-and-config.md](./references/schema-and-config.md) | [schema-and-config.zh-CN.md](./references/schema-and-config.zh-CN.md)
- Troubleshooting & mode toggles: [troubleshooting.md](./references/troubleshooting.md) | [troubleshooting.zh-CN.md](./references/troubleshooting.zh-CN.md)
- Templates: `templates/en/` and `templates/zh/` (`global-gemini.full.md`, `global-gemini.index-only.md`, `runbook.md`), plus `templates/shared/` (`memory-entry.md`, `sidecar-schedule.json`).
- Sanitized MilkFrog demo vault: [examples/milkfrog-demo/](./examples/milkfrog-demo/)

---

## Verification

1. Run final lint check and read the generated report (`~/.gemini/memory-ops/work/lint-<today>.md`):
   ```bash
   <PYTHON_CMD> ~/.gemini/memory-ops/memsync.py lint
   ```
   Confirm `errors=0`.
2. If `agents_cache_enabled=true`, verify `sync-plan` reports `0` unexpected drift right after initial setup.
3. Report to the user:
   - Exact files created/modified + backup paths (if migrated)
   - Active flags (`agents_cache_enabled`, `schedule_enabled`, `limits.profile`, `context_hook`, `lang`)
   - If the context hook was installed, note that `[milkfrog-context-hook](customization://milkfrog-context-hook)` is active from the next user turn and can be toggled live in Customizations UI or uninstalled anytime with `memsync.py hook uninstall`.
   - Note clearly: daily operation is now handled by `~/.gemini/GEMINI.md`, so this skill can safely be disabled or removed until needed for customization or future upgrades.

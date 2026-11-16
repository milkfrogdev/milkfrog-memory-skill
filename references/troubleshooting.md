# Troubleshooting & Customization Guide

## 1. Switching Between Dual-Layer and Index-Only Modes

- **Disable `AGENTS.md` caching after installing**:
  ```bash
  python3 ~/.gemini/memory-ops/memsync.py config set --agents-cache off
  ```
  This automatically turns off `schedule_enabled` as well. Replace `~/.gemini/GEMINI.md` header text with the index-only header from `templates/*/global-gemini.index-only.md` if you want the instructions to stop referencing `AGENTS.md`. Delete `~/.gemini/AGENTS.md` or `<workspace>/AGENTS.md` only if you no longer want them; `lint` will ignore them either way.
- **Re-enable dual-layer caching**:
  ```bash
  python3 ~/.gemini/memory-ops/memsync.py config set --agents-cache on
  python3 ~/.gemini/memory-ops/memsync.py sync-plan
  ```

## 2. Antigravity 24 KB Rule Truncation (`standard` vs `extended`)

Antigravity IDE truncates any single `GEMINI.md` or `AGENTS.md` larger than `24,000` bytes and drops lower-priority inline rules past `20,000` tokens.
- Keep `limits.profile = "standard"` unless you have explicitly modified your IDE limits.
- When `lint` warns on size: compress verbose index bullets, archive completed `project` entries, or merge fragmented notes under the same slug.

## 3. Antigravity CLI (`agy`) Not Supported

This skill targets **Antigravity IDE** rule loading (`~/.gemini/GEMINI.md`, workspace `GEMINI.md` / `AGENTS.md`) and Antigravity IDE background schedule sidecars (`~/.gemini/config/sidecars/`). It has **not** been tested or adapted for Antigravity CLI (`agy`).

## 4. Windows Python Command Differences

Windows users frequently lack `python3` in `PATH` and have `python` or `py -3` instead (the Windows Store `python3.exe` alias can fail if Python came from `python.org`). During setup, detect which exact binary runs `memsync.py --help` and embed that exact command in `GEMINI.md`, `RUNBOOK.md`, and `sidecar.json` `access_grants`.

## 5. Scheduled Automation Permissions (Antigravity Sidecars)

Antigravity runs scheduled sidecars unattended and denies non-whitelisted commands silently. After creating `sidecar.json`:
1. Never manually edit `user_config.json` to force-enable it.
2. Enable **Daily Memory Snapshot Sync** inside the Antigravity **Automations** dashboard.
3. Run a test turn once interactively to verify `command(...)`, `read_file(...)`, and `write_file(...)` grants match the exact commands your platform needs.

## 6. Clean Uninstall / Rollback

Every overwrite performed by `memsync.py` (including pre-migration `GEMINI.md` / `AGENTS.md` and `copy-global`) stores timestamped backups under `~/.gemini/memory-ops/backup/`. To revert cleanly:
1. Disable/remove `daily-agents-memory-sync` in Antigravity Automations and delete `~/.gemini/config/sidecars/daily-agents-memory-sync/`.
2. Restore your previous `GEMINI.md` / `AGENTS.md` files from `~/.gemini/memory-ops/backup/` if applicable.
3. Remove `~/.gemini/memory-ops/` (leave `~/.gemini/memories/` if you want to keep your curated Markdown notes).

# Memory System · Global Index & Protocol

This setup uses a two-tier `GEMINI.md` (index + entry bodies) and `AGENTS.md` (auto-distilled hot snapshot cache) architecture (for architecture details or customization, see `{{OPS_DIR}}/DESIGN.md`):
- **Global Memory**: Index at the bottom of this file; entry files in `{{MEMORY_HOME}}/memories/`.
- **Workspace Memory**: Index at `<workspace>/GEMINI.md`; entry files in `<workspace>/.gemini/memories/`.
- **Hot Snapshot Cache**: `{{MEMORY_HOME}}/AGENTS.md` and `<workspace>/AGENTS.md` are auto-generated via `memsync.py apply`. **Never edit managed `AGENTS.md` files by hand.**
- **Operations CLI**: `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" <subcommand>` (mode flags and workspace list live in `{{OPS_DIR}}/config.json`).

## Read & Write Protocol

0. **Zero-Command New Workspace Onboarding (interactive user-facing sessions with an open local folder only; strictly skip in cron/subagent/empty sessions)**:
   - When the active folder and all its parent folders are missing from `## Registered Workspaces` below (if nested inside a registered parent workspace, reuse the parent memory directly), missing from ignored paths, and lack `<workspace>/GEMINI.md`, ask on the first turn:
   - **No existing `AGENTS.md`**: Ask whether to initialize memory for this folder (plus an optional one-line summary). On approval, run `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" init "<dir>" --summary "<summary>"`; for throwaway folders, run `ws ignore "<dir>"`.
   - **Existing foreign `AGENTS.md` found**: Read it first without modifying it and offer three choices: 1) **Ignore folder** (`ws ignore`); 2) **Keep original `AGENTS.md` unmanaged** (`init "<dir>" --no-manage-agents --summary "<summary>"`, creating only `GEMINI.md` + `.gemini/memories/`); 3) **Translate & migrate into this system (Recommended)**: present a clear Keep (target scope + entry type + new/merged slug) vs Drop verdict table for user approval, back up the original into `backup/`, write entries + index, then run `sync-plan -> apply`.
1. **Read (selective)**: Scan `AGENTS.md` snapshots and both index lists before editing code, touching configs, or debugging; read only matching entry files (<= 5 per turn). Fix or remove stale facts immediately when noticed.
2. **Write (two-stage: immediate capture + post-task curation)**: (a) **Immediate capture**: persist **user-stated bans, corrections, or permanent rules**, plus **reusable pitfalls, broken flags, or workarounds the agent just verified** (unless already in a global Skill), in the same turn or sub-step instead of waiting for a long task to finish; at **>=80%** context alert or before compaction, save any unwritten durable items first; (b) **Post-task curation**: review remaining insights after tasks or sub-milestones. Never duplicate global Skill guidance, one-off ephemera, visible codebase structure, README facts, or git history.
3. **Scope Split (no double-writing)**: Preferences, general engineering conventions, and machine tools go to global; single-workspace progress, architecture choices, and repo-specific gotchas go to that project.
4. **Four Entry Types**:
   - `user`: User persona, style, typography, formatting, and collaboration boundaries.
   - `project`: Ongoing initiatives, decisions, blockers, milestones, and next steps.
   - `feedback`: General coding/architecture/UI/testing conventions, explicit user corrections, **agent-discovered or corrected pitfalls**, and hard redlines.
   - `reference`: Keep two patterns strictly separate — 1) **Single canonical toolchain registry**: merge all local SDKs, binary paths, package mirrors, proxy settings, **discovered CLI/flag pitfalls**, and OS gotchas into **`memories/local-installed-tools.md`** (`sync: auto`, so Section 4 of global `AGENTS.md` always distills an up-to-date quick reference instead of fragmenting per tool); 2) External service playbooks & secret location **pointers** in separate files marked `sync: never` (never plain-text secrets).
5. **Write Format & Verification**:
   - Search existing entries first and merge into the same topic file (updating `updated`) instead of spawning duplicates. Include YAML frontmatter (`name`, `description: [YYYY-MM-DD tag] one-line summary`, `type`, `scope`, `updated`, optional `digest`, `sync: auto|never`), plus `**Why:**` and `**How to apply:**` on `feedback` and `project` entries.
   - Re-read the target `GEMINI.md` before inserting/updating a single index bullet: `- [YYYY-MM-DD type·tag][Title](memories/<slug>.md) - one-line takeaway` (`.gemini/memories/<slug>.md` in projects).
   - Ensure `.gemini/memories/` is in `.gitignore` for git repos, and run `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" lint` after memory edits (active budget profile: `{{BUDGET_PROFILE}}`).

## Registered Workspaces

## Global Index

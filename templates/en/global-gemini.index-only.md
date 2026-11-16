# Memory System · Global Index & Protocol (Index-Only Mode)

This setup uses a lean two-tier `GEMINI.md` index + `memories/*.md` architecture without `AGENTS.md` snapshot caching or background cron tasks (for architecture details or switching modes, see `{{OPS_DIR}}/DESIGN.md`):
- **Global Memory**: Index at the bottom of this file; entry files in `{{MEMORY_HOME}}/memories/`.
- **Workspace Memory**: Index at `<workspace>/GEMINI.md`; entry files in `<workspace>/.gemini/memories/`.
- **Operations CLI**: `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" <subcommand>` (mode flags and workspace list live in `{{OPS_DIR}}/config.json`).

## Read & Write Protocol

0. **Zero-Command New Workspace Onboarding (interactive user-facing sessions with an open local folder only; strictly skip in background/subagent/empty sessions)**:
   - When the open folder and its parents are not in `## Registered Workspaces` (nested subfolders inherit their registered parent), not ignored, and lack `<workspace>/GEMINI.md`, ask once on the first turn whether to initialize memory or ignore the directory:
   - Run `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" init "<dir>" --summary "<summary>"` on approval, or `ws ignore "<dir>"` for temporary folders.
   - If a repo already has an existing `AGENTS.md`, index-only mode leaves it untouched by default; offer to translate durable rules into `GEMINI.md` + `.gemini/memories/*.md` after showing a Keep/Drop table.
1. **Read (selective)**: Scan global and workspace `GEMINI.md` indexes before starting work; load matching entry files on demand (<= 5 per turn) and update stale entries immediately.
2. **Write (post-task curation)**: Record durable insights only after finishing meaningful work; skip transient session details, raw directory trees, and git logs.
3. **Scope Split (no double-writing)**: Cross-project conventions, user preferences, and shared tooling belong in global; single-project progress and local pitfalls belong in that project.
4. **Four Entry Types**: `user` (preferences & style), `project` (status & decisions), `feedback` (coding conventions & corrections), `reference` (merge all local tool paths, package mirrors, and OS gotchas into the single canonical `memories/local-installed-tools.md` entry; put external manuals & secret pointers in separate `sync: never` files without plain-text secrets).
5. **Write Format & Verification**:
   - Check for an existing file on the same topic first and merge updates rather than duplicating; require YAML frontmatter (`name`, `description: [YYYY-MM-DD tag] one-line summary`, `type`, `scope`, `updated`), plus `**Why:**` and `**How to apply:**` on `feedback`/`project` entries.
   - Re-read target `GEMINI.md` before editing a single index line: `- [YYYY-MM-DD type·tag][Title](memories/<slug>.md) - takeaway` (`.gemini/memories/<slug>.md` in projects).
   - Keep `.gemini/memories/` in `.gitignore` for git repos, and run `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" lint` after every memory change (active budget profile: `{{BUDGET_PROFILE}}`).

## Registered Workspaces

## Global Index

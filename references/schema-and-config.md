# Schema, State Flags & CLI Reference

## 1. `config.json` State Flags (`~/.gemini/memory-ops/config.json`)

If an older `~/.gemini/memory-ops/workspaces.json` exists and `config.json` does not, `memsync.py` reads `workspaces.json` automatically and applies v2 defaults.

| Key | Type | Default | Behavior |
| --- | --- | --- | --- |
| `lang` | `"zh" \| "en"` | `"zh"` | Controls generated `GEMINI.md`/`AGENTS.md` headings & init text (`lint` accepts both headings). |
| `mode.agents_cache_enabled` | `bool` | `true` | `true`: Dual-layer (`GEMINI.md` + `AGENTS.md`); `false`: Index-only (`GEMINI.md` only). |
| `mode.schedule_enabled` | `bool` | `false` | Records whether automated Antigravity cron sync is active. Forced `false` when `agents_cache_enabled` is `false`. |
| `mode.auto_discover_unregistered` | `bool` | `true` | When `true`, `lint` checks `~/.gemini/config/projects` for uninitialized folders. |
| `schedule.time` | `HH:MM` | `"06:00"` | Display/cron target time stored in `sidecar.json` and `AGENTS.md` headers. |
| `schedule.timezone` | IANA zone | auto-detected | Passed as `CRON_TZ=<zone>` in Antigravity `sidecar.json`. |
| `limits.profile` | `"standard" \| "extended"` | `"standard"` | `"standard"` enforces 24KB hard file cap; `"extended"` unlocks 160KB/96KB caps. |
| `limits.custom` | `object` (optional) | omitted | Partial overrides for `global`, `project`, `rules_total_warn`, `rules_total_hard`. |
| `cross_tool_sync.enabled` | `bool` | `false` | Enables copying global `AGENTS.md` to external agent directories on `apply --scope global`. |
| `cross_tool_sync.targets` | `{name: path}` | `{}` | Map of external targets, e.g. `{"codex": "~/.codex/AGENTS.md", "claude": "~/.claude/CLAUDE.md"}`. |
| `workspaces[]` | `array` | `[]` | Each entry: `{name, path, summary, enabled, manage_agents?}`. Setting `manage_agents: false` keeps an existing foreign `AGENTS.md` untouched in that single repo. |
| `ignored[]` | `array` | `[]` | Throwaway paths suppressed from new-workspace discovery: `{path, reason, added}`. |

## 2. Entry YAML Frontmatter Specification

Each `memories/<slug>.md` file (global or `<workspace>/.gemini/memories/<slug>.md`) must include:

```yaml
---
name: unique-kebab-case-slug
description: [2026-11-16 decision] One-line summary of the rule or finding
digest: Optional <=60 char teaser
metadata:
  type: user | feedback | project | reference
  scope: global | project
  created: 2026-11-16
  updated: 2026-11-16
  sync: auto | never
---
```

Notes:
- `name` must match the file stem (`<slug>`).
- `scope` must match the parent directory (`global` under `~/.gemini/memories/`, `project` under `<ws>/.gemini/memories/`).
- Local software paths, package mirrors, proxy configs, and OS quirks should be merged into the single canonical global entry `memories/local-installed-tools.md` (`type: reference`, `sync: auto`). Keep secret/credential pointers in separate `sync: never` files.
- Append `**Why:**` and `**How to apply:**` sections on `feedback` and `project` entries.
- Matching index line format in `GEMINI.md`:
  `- [YYYY-MM-DD type·tag][Title](memories/<slug>.md) - concise takeaway` (or Chinese `- 【YYYY-MM-DD 类型·定性】[标题](memories/<slug>.md) — 结论`).

## 3. `memsync.py` CLI Commands

Environment override for isolated testing or non-default paths:
- `MILKFROG_MEMORY_HOME`: overrides `~/.gemini` root directory.

Subcommands:
- `doctor [--json]`: Read-only inspection of Python, OS, timezone, existing `GEMINI.md`/`AGENTS.md`, `memories/local-installed-tools.md`, external tools (`~/.codex`, `~/.claude`), common CLI toolchains on `PATH` (`detected_toolchains`), and Antigravity projects.
- `bootstrap [--lang zh|en] [--agents-cache on|off] [--schedule on|off] [--schedule-time HH:MM] [--timezone TZ] [--profile standard|extended] [--auto-discover on|off] [--target name=path] [--no-global-files] [--force-global]`: Idempotently sets up `memory-ops/` and writes `config.json`.
- `config show`: Prints normalized `config.json`.
- `config set [--lang zh|en] [--agents-cache on|off] [--schedule on|off] [--auto-discover on|off] [--profile standard|extended] [--cross-sync on|off] [--add-target name=path] [--remove-target name]`: Updates state flags without editing files manually.
- `lint`: Audits all enabled scopes, links, frontmatter, secrets, budgets, `.gitignore`, and unregistered folders; writes `work/lint-YYYY-MM-DD.md`.
- `sync-plan`: Detects SHA256 diffs across enabled workspaces and global memories; writes `work/sync-plan-YYYY-MM-DD.md` and per-workspace `sync-ws-<id>-YYYY-MM-DD.md`.
- `global-input`: Packages Stage-1 workspace snapshots + global diffs into `work/sync-global-YYYY-MM-DD.md`.
- `apply --scope <global|ws> <draft.md> [--dry-run] [--no-copy]`: Validates draft, backs up old `AGENTS.md`, writes new `AGENTS.md`, updates `sync-state.json`, and mirrors to external targets if enabled.
- `init <path> [--summary "..."] [--name <slug>] [--disabled] [--allow-nested] [--force-agents] [--no-manage-agents]`: Initializes a workspace directory and registers it.
- `ws list | add | ignore | unignore | enable | disable | manage-agents`: Manages workspace registry and per-workspace `manage_agents` flags.
- `copy-global [--targets a,b] [--dry-run]`: Manually mirrors global `AGENTS.md` to configured `cross_tool_sync.targets`.

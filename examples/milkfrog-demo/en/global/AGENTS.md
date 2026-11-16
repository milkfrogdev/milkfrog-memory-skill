# AGENTS.md (Global Snapshot · Sample)

> Auto-generated snapshot maintained via `memsync` (06:00 / on-demand). Do not edit manually.
> **Full Memory Entrypoint**: [GEMINI.md](GEMINI.md) | Entries directory: `memories/`

## 1. User Profile & Core Preferences

- **Brand & Typography (MilkFrog)**: Use sans-serif fonts (`Arial`, `Segoe UI`, `sans-serif`) everywhere across UI, docs, and diagrams; never use serif fonts. Keep docs direct and concrete with zero AI wrap-up cliches.

## 2. Workspaces & Active Projects

- **`milkfrog-blog` (`/path/to/workspaces/milkfrog-blog`)**: Open-source static blog demo; static build and tag pagination work, next up are `/rss.xml` generation and flicker-free dark mode toggle.

## 3. General Engineering Conventions

- **Evidence First**: Report only tests and commands executed after the final edit; state exact scope and any failures.
- **Reversible Config Changes**: Back up existing configs and state what changed plus how to revert.
- **Clean Repos**: Keep scratch probes in session scratch folders and add `.gemini/memories/` to `.gitignore`.

## 4. Environment & Tooling Quick Reference

- **Runtime & Packages**: System `python3` (stdlib-only memory ops), LTS Node + `pnpm`, default Git branch `main`.
- **Credential Pointers (`sync: never`)**: Demo token path lives in [secret-env-pointer.md](memories/secret-env-pointer.md) with zero plain-text secrets.
- **Canonical Tooling Registry**: Full local tool details and OS conventions live in [local-installed-tools.md](memories/local-installed-tools.md).

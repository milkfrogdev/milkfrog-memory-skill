# AGENTS.md (milkfrog-blog Workspace Snapshot · Sample)

> Auto-generated snapshot maintained via `memsync` (06:00 / on-demand). Do not edit manually.
> Workspace: milkfrog-blog (`/path/to/workspaces/milkfrog-blog`) | Summary: MilkFrog open-source static technical blog demo | Last synced: 2026-11-16
> **Memory Entrypoints**: [GEMINI.md](GEMINI.md) (entries in `.gemini/memories/`); global conventions live in global `GEMINI.md`.

## 1. Active Project Progress & Decisions

- **Shipped**: Static build, frontmatter parsing, and tag pagination (10/page) work; search uses a build-time JSON index without any backend DB.
- **Next**: Add `/rss.xml` feed generation and a dark theme toggle.

## 2. Project-Specific Conventions & Pitfalls

- **Static-Only Boundary**: Keep the site purely static with no runtime server dependencies; keep typography strictly sans-serif.

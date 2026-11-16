---
name: blog-rss-roadmap
description: [2026-11-16 project·sample] MilkFrog demo blog status and next milestones
digest: Tag filtering and static build work; next are RSS feed and dark mode
metadata:
  type: project
  scope: project
  created: 2026-11-16
  updated: 2026-11-16
  sync: auto
---

# MilkFrog Blog Demo Progress (Sample)

- **Shipped**: Static build pipeline, Markdown frontmatter parser, tag filtering, and 10-posts-per-page pagination.
- **Decision**: Emit a static search JSON index during build time instead of running a backend search service.
- **Next**: Add `/rss.xml` feed generation and a flicker-free system-default + manual dark theme toggle (sans-serif typography).

**Why:** Personal technical blogs stay low-maintenance when deployed as pure static assets without a database.
**How to apply:** Check static search JSON bundle size and RSS XML schema tests before shipping new blog features.

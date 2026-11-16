---
name: example-entry-slug
description: [YYYY-MM-DD source-tag] One-line conclusion describing when to read this entry
digest: Optional <=60 chars summary for compact scanning
metadata:
  type: feedback
  scope: global
  created: YYYY-MM-DD
  updated: YYYY-MM-DD
  sync: auto
---

# Title

Replace with actionable facts, decisions, exact paths/constraints, or gotchas.

- Keep content focused on one topic so future updates can merge cleanly into this file.
- For `type: reference` holding pointer info to local secrets/credentials, set `sync: never` above and NEVER include plain-text passwords, API keys, or private tokens here.

**Why:** Explain why this rule or decision exists so future agents do not regress it without context.
**How to apply:** State clearly when and how this rule or decision applies (required for `feedback` and `project` entries).

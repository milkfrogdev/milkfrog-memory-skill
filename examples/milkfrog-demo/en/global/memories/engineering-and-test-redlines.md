---
name: engineering-and-test-redlines
description: [2026-11-16 feedback·sample] Real test verification, config rollback notes, and clean workspace rules
digest: Run real tests after final edit; explain rollback on config edits
metadata:
  type: feedback
  scope: global
  created: 2026-11-16
  updated: 2026-11-16
  sync: auto
---

# Engineering & Verification Redlines (Sample)

1. **Report Verified Runs Only**: Run relevant tests after the final edit and report exact command results and skipped cases rather than guessing.
2. **Explain Rollback**: Before modifying user config files or automation settings, keep a backup and state exactly what changed and how to revert it.
3. **Keep Workspaces Clean**: Put temporary test probes in scratch folders rather than polluting project roots.

**Why:** Agents sometimes report unverified assumptions or overwrite local settings silently.
**How to apply:** Execute unit tests on every code change and preserve backups before touching any existing configuration.

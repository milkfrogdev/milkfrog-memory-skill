---
name: secret-env-pointer
description: [2026-11-16 reference·redacted] Credential & deploy token location pointer (sync: never, zero plain-text secrets)
digest: Demonstrates sync:never credential pointer separated from toolchain registry
metadata:
  type: reference
  scope: global
  created: 2026-11-16
  updated: 2026-11-16
  sync: never
---

# Credential Storage Pointers (Sample)

- **Demo Blog Deploy Token & Local Env**: Stored at `~/.config/milkfrog-demo/.env.local`.
- **Rule**: Record file paths or variable names only, never plain-text secret values. Because `sync: never` is set, snapshot sync omits this body from `sync-state.json`.

---
name: local-installed-tools
description: [2026-11-16 reference·sample] Single canonical local toolchain, package manager, and OS environment registry (sync: auto)
digest: Canonical toolchain sample: Python3/Node/pnpm/Git conventions (sync: auto)
metadata:
  type: reference
  scope: global
  created: 2026-11-16
  updated: 2026-11-16
  sync: auto
---

# Local Installed Tools & Environment Registry (Sample)

> Single canonical registry (`sync: auto`) for local tool paths, package managers, and OS quirks; Section 4 of global `AGENTS.md` summarizes this entry and links back here. Keep credential pointers in separate `sync: never` files (see [[secret-env-pointer]]).

- **Python**: System `python3` (`>= 3.9`), stdlib-only memory scripts.
- **Node / Package Manager**: LTS Node + `pnpm`.
- **Git**: Default branch `main`; verify repo-local `user.name/email` before committing to open-source repos.

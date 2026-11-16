---
name: local-installed-tools
description: 【2026-11-16 参考·示例】本机常用开发工具链、包管理器与环境约定唯一正本（sync: auto）
digest: 唯一工具正本示例：Python3/Node/pnpm/Git/OS 约定（sync: auto）
metadata:
  type: reference
  scope: global
  created: 2026-11-16
  updated: 2026-11-16
  sync: auto
---

# 本机已安装工具与环境速查（唯一真相源 · 示例）

> 本文件作为全局软件路径、包管理器与系统环境坑的唯一正本（`sync: auto`）；全局 `AGENTS.md` 第四节只提炼简短速查并指向本篇。涉及密钥或私钥的位置指针另建 `sync: never` 文件存放（见 [[secret-env-pointer]]）。

- **Python**：系统 `python3`（3.9+），记忆脚本仅用标准库。
- **Node / 包管理**：LTS Node + `pnpm`。
- **Git**：默认主分支名 `main`，提交前用仓级 `user.name/email` 核对开源身份。

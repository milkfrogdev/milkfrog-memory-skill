---
name: secret-env-pointer
description: 【2026-11-16 参考·保密示例】敏感凭据与部署 Token 存放指针（sync: never，不含任何明文）
digest: 演示用 sync:never 敏感配置指针写法，只存文件路径不存明文密钥
metadata:
  type: reference
  scope: global
  created: 2026-11-16
  updated: 2026-11-16
  sync: never
---

# 敏感凭据存放指针（示例）

- **演示博客部署 Token 与本地环境变量**：存放在 `~/.config/milkfrog-demo/.env.local`。
- **安全约定**：记忆正文和 `AGENTS.md` 永远只记录文件位置或变量名，不写明文值；本文件因标记 `sync: never`，同步脚本不会缓存正文进 `sync-state.json`。

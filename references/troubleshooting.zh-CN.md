# 常见排障与模式切换指南

## 1. 在「双层模式」与「纯索引模式」之间切换

- **装完后想关掉 `AGENTS.md` 缓存，改成纯索引模式**：
  ```bash
  python ~/.gemini/memory-ops/memsync.py config set --agents-cache off
  ```
  该命令会联动关闭 `schedule_enabled`。随后可把 `~/.gemini/GEMINI.md` 头部换成纯索引版文案，原有 `AGENTS.md` 文件无论留还是删都不会再触发 `lint` 告警。
- **以后想重新打开双层模式**：
  ```bash
  python ~/.gemini/memory-ops/memsync.py config set --agents-cache on
  python ~/.gemini/memory-ops/memsync.py sync-plan
  ```

## 2. Antigravity 原生 24 KB 文件上限问题

原版 Antigravity IDE 对单个 `GEMINI.md` / `AGENTS.md` 有 `24,000` 字节硬限制（超出会按行静默截断），全部常驻规则共用 `20,000` tokens 预算：
- 除非你确认自己已经通过补丁解除了上限，否则保持默认的 `"profile": "standard"`。
- `lint` 提示体积接近上限时，把偏长的索引行压缩成一句话、归档已完全结项的 `project` 条目，或者把同主题碎文件合并成一篇。

## 3. 暂不支持 Antigravity CLI（`agy`）

本 Skill 目前只针对 **Antigravity IDE** 的规则发现与后台自动化 sidecar 设计并实测过，**未对 Antigravity CLI（`agy`）做过兼容适配与验证**。如果要在 Claude Code / Codex 等终端 Agent 使用，请关闭定时 sidecar，用手动触发方式运行 `memsync.py` 同步或直接采用纯索引模式。

## 4. Windows 下 `python` / `python3` / `py -3` 识别坑

Windows 上装了官网 Python 后往往只有 `python` 或 `py -3`，系统自带的 `python3.exe` 可能是微软商店空壳跳板。安装阶段务必由 Agent 先实测一次哪条命令能真跑通 `memsync.py --help`，再把该命令写入 `GEMINI.md`、`RUNBOOK.md` 和 `sidecar.json` 的 `access_grants`。

## 5. 后台定时任务权限未放行

Antigravity 定时自动化在无人值守会话里运行，没放行在 `access_grants` 里的命令会被静默拒绝。生成 `sidecar.json` 后：
1. 不要直接修改 `user_config.json` 强制激活。
2. 到 Antigravity **Automations** 面板手动启用定时任务。
3. 建议先在对话里试跑一次完整同步，确认 `command(...)`、`read_file(...)`、`write_file(...)` 与工作区 URI 权限全部精准匹配当前环境。

## 6. 彻底卸载与回滚

`memsync.py` 每次覆盖原有 `GEMINI.md`、`AGENTS.md` 或跨端目标文件前，都会在 `~/.gemini/memory-ops/backup/` 留带时间戳备份。如需撤回：
1. 在 Antigravity Automations 面板关闭并删掉 `~/.gemini/config/sidecars/daily-agents-memory-sync/`。
2. 需要的话从 `~/.gemini/memory-ops/backup/` 找回迁入前的原版 `GEMINI.md` / `AGENTS.md`。
3. 删除 `~/.gemini/memory-ops/`（纯正文笔记在 `~/.gemini/memories/`，可按需保留）。

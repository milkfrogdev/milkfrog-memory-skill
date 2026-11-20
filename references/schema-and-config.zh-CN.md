# 配置字段、Frontmatter 规范与脚本命令手册

## 1. `config.json` 状态位说明（`~/.gemini/memory-ops/config.json`）

如果用户机器里原本只有旧版 `~/.gemini/memory-ops/workspaces.json`，`memsync.py` 会自动兼容读取并补全 v2 默认字段。

| 字段 | 类型 | 默认值 | 作用说明 |
| --- | --- | --- | --- |
| `lang` | `"zh" \| "en"` | `"zh"` | 控制生成模板的语言和标题（`lint` 同时兼容中英文标题）。 |
| `mode.agents_cache_enabled` | `bool` | `true` | `true`：双层（`GEMINI.md` + `AGENTS.md`）；`false`：纯索引（只留 `GEMINI.md`）。 |
| `mode.schedule_enabled` | `bool` | `false` | 标记是否开启后台定时同步。若关闭 `agents_cache_enabled`，此项自动置 `false`。 |
| `mode.auto_discover_unregistered` | `bool` | `true` | 为 `true` 时，`lint` 会扫描 `~/.gemini/config/projects` 提示未纳管工作区。 |
| `schedule.time` | `HH:MM` | `"06:00"` | 定时同步触发时间（用于 `sidecar.json` cron 与快照头部文案）。 |
| `schedule.timezone` | IANA 时区 | 自动探测 | 填入 `sidecar.json` 的 `CRON_TZ=<时区>` 前缀。 |
| `limits.profile` | `"standard" \| "extended"` | `"standard"` | `standard` 严卡 24KB 原生文件上限；`extended` 适用于已扩容上下文的环境。 |
| `limits.custom` | `object`（可选） | 省略 | 按需覆盖 `global`、`project`、`rules_total_warn`、`rules_total_hard` 字节数。 |
| `cross_tool_sync.enabled` | `bool` | `false` | 是否在更新全局 `AGENTS.md` 后顺带复制到其他 Agent 配置。 |
| `cross_tool_sync.targets` | `{name: path}` | `{}` | 外部目标映射，如 `{"codex": "~/.codex/AGENTS.md", "claude": "~/.claude/CLAUDE.md"}`。 |
| `context_hook.enabled` | `bool` | `false` | 控制 `context_hook.py` 是否注入上下文占用（配合 `milkfrog-context-hook` 插件）。 |
| `context_hook.mode` | `"always" \| "threshold"` | `"always"` | `"always"`：每次推理都注精简占用、达线加抢救提醒；`"threshold"`：仅达 `warn_percent` 以上注入。 |
| `context_hook.warn_percent` | `number` | `80` | 触发记忆抢救提醒的百分比阈值（`1–99`）。 |
| `workspaces[]` | `array` | `[]` | 每项 `{name, path, summary, enabled, manage_agents?}`；单仓库设 `manage_agents: false` 可永久保留他人原版 `AGENTS.md`。 |
| `ignored[]` | `array` | `[]` | 忽略目录列表 `{path, reason, added}`，跳过新工作区初始化提示。 |

## 2. 记忆条目 YAML Frontmatter 规范

全局 `~/.gemini/memories/<slug>.md` 与项目 `<workspace>/.gemini/memories/<slug>.md` 头部必须带以下字段：

```yaml
---
name: unique-kebab-case-slug
description: 【2026-11-16 定性】一句话说明结论与触发场景
digest: 可选，不超过 60 字的摘要
metadata:
  type: user | feedback | project | reference
  scope: global | project
  created: 2026-11-16
  updated: 2026-11-16
  sync: auto | never
---
```

约束要点：
- `name` 必须与文件名（去掉 `.md`）完全一致。
- `scope` 必须与所在目录一致（全局写 `global`，工作区写 `project`）。
- 本机软件路径、SDK 版本、镜像源与系统级环境坑统一合并进全局 **`memories/local-installed-tools.md`**（`type: reference`、`sync: auto`），密钥/服务器凭据指针单独建 `sync: never` 文件存放。
- `feedback` 与 `project` 条目正文末尾须附 `**Why:**` 与 `**How to apply:**`。
- 对应 `GEMINI.md` 索引单行格式：`- 【YYYY-MM-DD 类型·定性】[标题](memories/<slug>.md) — 结论`（或英文 `- [YYYY-MM-DD ...]`）。

## 3. `memsync.py` 子命令速查

支持通过环境变量 `MILKFROG_MEMORY_HOME` 覆盖默认 `~/.gemini` 路径（用于沙箱隔离测试或自定义目录）。

- `doctor [--json]`：只读检查 Python 版本、OS、时区、已有 `GEMINI.md`/`AGENTS.md`、`memories/local-installed-tools.md`、外部工具目录、`PATH` 上常见开发命令（`detected_toolchains`）与 Antigravity 项目列表，不改动任何文件。
- `bootstrap [--lang zh|en] [--agents-cache on|off] [--schedule on|off] [--schedule-time HH:MM] [--timezone TZ] [--profile standard|extended] [--auto-discover on|off] [--context-hook on|off] [--hook-mode always|threshold] [--hook-warn N] [--target name=path] [--no-global-files] [--force-global]`：幂等建好 `memory-ops/` 目录与 `config.json`（传入 `--context-hook on` 会顺带安装 `milkfrog-context-hook` 插件）。
- `config show`：查看当前归一化后的 `config.json`。
- `config set [--lang zh|en] [--agents-cache on|off] [--schedule on|off] [--auto-discover on|off] [--profile standard|extended] [--context-hook on|off] [--hook-mode always|threshold] [--hook-warn N] [--cross-sync on|off] [--add-target name=path] [--remove-target name]`：随时调整模式开关、Hook 策略与阈值档位。
- `hook install [--script PATH] [--python CMD] [--mode always|threshold] [--warn-percent N]`：复制 `context_hook.py` 到 `memory-ops/` 并自动写入 `~/.gemini/config/plugins/milkfrog-context-hook/`（`plugin.json` + `hooks.json`）。
- `hook status`：查看 Hook 配置与插件安装状态。
- `hook uninstall`：备份 `hooks.json` 后移除 `milkfrog-context-hook` 并把 `context_hook.enabled` 置 `false`。
- `lint`：检查各启用作用域结构、链接、frontmatter、疑似明文密钥、字节阈值、`.gitignore` 与未初始化工作区，输出报告到 `work/lint-YYYY-MM-DD.md`。
- `sync-plan`：做阶段 1（工作区）+ 阶段 2（全局）sha256 diff 检测，跳过无变化作用域，生成 `work/sync-plan-YYYY-MM-DD.md` 和 `sync-ws-<id>-YYYY-MM-DD.md`。
- `global-input`：把阶段 1 更新后的工作区快照与全局 diff 打包为 `work/sync-global-YYYY-MM-DD.md`。
- `apply --scope <global|ws> <draft.md> [--dry-run] [--no-copy]`：校验草稿（不含密钥、带指针、未超限）、备份旧版、写入正式 `AGENTS.md`、更新 `sync-state.json`，按需执行跨端分发。
- `init <path> [--summary "..."] [--name <slug>] [--disabled] [--allow-nested] [--force-agents] [--no-manage-agents]`：幂等初始化工作区。
- `ws list | add | ignore | unignore | enable | disable | manage-agents`：查看或维护工作区注册表与单仓开关。
- `copy-global [--targets a,b] [--dry-run]`：手动把全局 `AGENTS.md` 备份并复制到外部工具目录。

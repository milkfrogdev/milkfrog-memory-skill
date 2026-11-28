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
| `context_hook.mode` | `"threshold" \| "always"` | `"threshold"` | `"threshold"`：默认，仅达 `warn_percent` 以上注入抢救提醒，低水位静默；`"always"`：每次推理都注精简占用、达线加抢救提醒。 |
| `context_hook.warn_percent` | `number` | `80` | 触发记忆抢救提醒的百分比阈值（`1–99`）。 |
| `context_hook.cooldown_calls` | `int` | `3` | 高水位冷却步数：达到预警线后每 `N` 次模型调用最多提醒 1 次（`1` 表示不节流）。 |
| `context_hook.critical_percent` | `number` | `92` | 危急破例阈值（`1–100`，`0` 关闭）：冷却期内首次冲过该线立即补提醒 1 次。 |
| `workspaces[]` | `array` | `[]` | 每项 `{name, path, summary, sync_mode}`：`full`（默认，本地快照+汇总全局）、`local`（独立隔离，仅更新本地快照不同步细节进全局）、`index`（不接管现有 `AGENTS.md`，仅用索引参与全局汇总）、`off`（停用）；向后兼容旧 `enabled`/`manage_agents`/`sync_to_global` 布尔字段。 |
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
- `bootstrap [--lang zh|en] [--agents-cache on|off] [--schedule on|off] [--schedule-time HH:MM] [--timezone TZ] [--profile standard|extended] [--auto-discover on|off] [--context-hook on|off] [--hook-mode threshold|always] [--hook-warn N] [--hook-cooldown N] [--hook-critical N] [--target name=path] [--no-global-files] [--force-global]`：幂等建好 `memory-ops/` 目录与 `config.json`（传入 `--context-hook on` 会顺带安装 `milkfrog-context-hook` 插件）。
- `config show`：查看当前归一化后的 `config.json`。
- `config set [--lang zh|en] [--agents-cache on|off] [--schedule on|off] [--auto-discover on|off] [--profile standard|extended] [--context-hook on|off] [--hook-mode threshold|always] [--hook-warn N] [--hook-cooldown N] [--hook-critical N] [--cross-sync on|off] [--add-target name=path] [--remove-target name]`：随时调整模式开关、Hook 策略与阈值档位。
- `hook install [--script PATH] [--python CMD] [--mode threshold|always] [--warn-percent N] [--cooldown N] [--critical-percent N]`：复制 `context_hook.py` 到 `memory-ops/` 并自动写入 `~/.gemini/config/plugins/milkfrog-context-hook/`（`plugin.json` + `hooks.json`）。
- `hook status`：查看 Hook 配置与插件安装状态。
- `hook uninstall`：备份 `hooks.json` 后移除 `milkfrog-context-hook` 并把 `context_hook.enabled` 置 `false`。
- `lint`：检查各启用作用域结构、链接、frontmatter、疑似明文密钥、字节阈值、`.gitignore` 与未初始化工作区，输出报告到 `work/lint-YYYY-MM-DD.md`。
- `sync-plan`：做阶段 1（工作区）+ 阶段 2（全局 `stage2_ws`/`stage2_mem`）sha256 diff 检测，跳过无变化作用域，生成 `work/sync-plan-YYYY-MM-DD.md` 和 `sync-ws-<id>-YYYY-MM-DD.md`（带 `n=4` 上下文与小节标题、长行词段级改动提示，并对 `≤ 4 KB` 修改文件内联完整正文；`sync_mode=local` 工作区仅更新本地、不触发阶段 2）。
- `global-input [--part all|ws|mem]`：支持按步打包——`--part ws` 仅输出工作区增量 diff、`[ISOLATED]` 定位锚点与当前全局 `## 二、` 原文（`sync-global-ws-*.md`）；`--part mem` 仅输出全局记忆 diff 与受影响板块原文（`sync-global-mem-*.md`）；默认 `all` 输出完整汇总包。
- `apply --scope <global|ws> [--section 2|1,3,4|ws|mem] [--state-part auto|all|ws|mem] <draft.md> [--dry-run] [--no-copy]`：支持整份写入或按同步块精准合并（未选板块原样保留并自动刷新头部日期、分步保留未刷新的基线），校验密钥/指针/字节阈值/日期/`[DELETED]` 残留，备份旧版、更新 `sync-state.json`、清理超期 `work/` 报告并按需跨端分发。
- `show <scope> <target> [--version current|before|both] [--stdout]`：跨工作区安全只读查阅任意作用域的记忆正文（含从 `sync-state.json` 提取的改前/删前旧版）、`AGENTS.md` 或 `GEMINI.md`；脚本层强制脱敏 `sync: never` 正文，定时任务无需追加工作区目录权限。
- `search <query> [--scope all|<id>] [--max-matches N] [--regex] [--stdout]`：纯 Python 跨作用域只读检索当前与已删除前记忆正文；对 `sync: never` 条目仅检安全元信息，绝不读取正文。
- `init <path> [--sync-mode full|local|index|off] [--summary "..."] [--name <slug>] [--allow-nested] [--force-agents]`：幂等初始化工作区（兼容旧标志 `--disabled` / `--no-manage-agents` / `--isolated`）。
- `ws list | add | mode <target> <full|local|index|off> | ignore | unignore | enable | disable | manage-agents | sync-global`：查看或维护工作区注册表与同步模式。
- `copy-global [--targets a,b] [--dry-run]`：手动把全局 `AGENTS.md` 备份并复制到外部工具目录。

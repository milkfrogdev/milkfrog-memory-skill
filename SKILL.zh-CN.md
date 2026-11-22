---
name: milkfrog-memory
description: >-
  为 Antigravity IDE 安装、迁移或二次定制 MilkFrog（程序员奶蛙）双层本地记忆系统
  （GEMINI.md 索引正文 + 可选 AGENTS.md 热缓存快照）。当用户需要部署跨会话记忆、
  迁移旧版 GEMINI.md/AGENTS.md、切换双层/纯索引模式、开启可选定时同步或改造
  memsync.py 时使用。暂不支持 Antigravity CLI (agy)。安装完成后日常全靠
  ~/.gemini/GEMINI.md 独立运行，不再依赖本 Skill。
---

# MilkFrog 双层记忆系统安装与迁移指南

English version: [SKILL.md](./SKILL.md)

## 目标与产出

在用户本机部署一套纯本地、零第三方依赖的 Markdown 记忆体系，根据用户偏好配置模式开关，带备份地迁移原有规则文件并跑通 `lint` 自检；完成后日常规则全量沉淀进 `~/.gemini/GEMINI.md` 头部，后续无需保留本 Skill 即可独立运行。

| 产出物 | 目标路径 | 作用 |
| --- | --- | --- |
| 运维脚本 | `~/.gemini/memory-ops/memsync.py` | 纯标准库 Python CLI（体检/校验/diff/落盘/工作区管理） |
| 状态配置 | `~/.gemini/memory-ops/config.json` | 记录模式开关（`agents_cache`、`schedule`、`limits`、`workspaces`） |
| 离线设计正本 | `~/.gemini/memory-ops/DESIGN.md` | 架构设计副本（方便删掉 Skill 后做二开或调参） |
| 全局入口 | `~/.gemini/GEMINI.md` | 内含完整日常读写规程、工作区清单与全局索引 |
| 全局正文 | `~/.gemini/memories/*.md` | `user / feedback / project / reference` 单一真相源 |
| 同步手册 *(开启缓存时)* | `~/.gemini/memory-ops/RUNBOOK.md` | 定时任务或手动蒸馏 `AGENTS.md` 的操作规程 |
| 全局快照 *(开启缓存时)* | `~/.gemini/AGENTS.md` | 由 `memsync apply` 生成的初始热缓存 |
| 上下文 Hook *(开启监控时)* | `~/.gemini/memory-ops/context_hook.py` 与 `~/.gemini/config/plugins/milkfrog-context-hook/` | 自动读取当前占用并在 >=80% 时提醒先落盘记忆的 `PreInvocation` 插件 |
| 定时 Sidecar *(开启定时时)* | `~/.gemini/config/sidecars/daily-agents-memory-sync/sidecar.json` | Antigravity IDE 后台 cron 配置（绝不静默代开） |

**完成标志**：使用实测可用的 Python 命令运行 `memsync.py lint` 返回 `errors=0`，所有改写前旧文件已备份，且日常读写不再依赖本 Skill。

---

## 宿主支持范围

- **支持**：**Antigravity IDE**（完整规则发现 + 可选后台 cron sidecar），并支持可选单向导出到 Codex / Claude Code（`~/.codex/AGENTS.md`、`~/.claude/CLAUDE.md`）。
- **暂不支持**：**Antigravity CLI（`agy`）** 尚未做过适配与实测。若用户在 `agy` CLI 中调用，先如实说明不支持再询问是否只部署纯手动命令行脚本。

---

## 步骤

### 第 1 步 · 只读环境体检（先查现状，再提问）

写任何文件之前，先只读检查：
1. 找一条真正能运行的 Python `>= 3.9` 命令（依次验证 `python3` / `python` / Windows `py -3` 能否跑通 `./scripts/memsync.py --help`，避开 Windows Store 空壳 `python3.exe`）。
2. 在 Skill 目录内只读运行环境扫描：
   ```bash
   <PYTHON_CMD> ./scripts/memsync.py doctor --json
   ```
3. 提取客观状态：OS 与本地时区、是否存在旧 `GEMINI.md` / `AGENTS.md` 与 `memories/local-installed-tools.md`、本机有哪些外部 Agent 目录（`~/.codex`、`~/.claude`）以及 `PATH` 上探测到的常用公共开发命令（`detected_toolchains`：`python`、`node`、`pnpm`、`uv`、`git`、`java`、`mvn`、`cargo`、`go`、`docker`，不扫任何私人目录），并按用户对话语言选定 `templates/zh/` 或 `templates/en/`。

### 第 2 步 · 一次性确认安装与兼容选项（`ask_question`）

只问跟当前环境相关的选项，别问无关问题：

1. **架构模式**：
   - `(Recommended) 双层模式：GEMINI.md 索引正文 + AGENTS.md 自动热缓存`（`agents_cache_enabled=true`）
   - `纯索引模式：只用 GEMINI.md 索引 + memories/*.md（不建 AGENTS.md、不开定时任务）`（`agents_cache_enabled=false`）
2. **后台定时蒸馏** *(仅选双层模式时问)*：
   - `(Recommended) 开启每日定时自动同步`（默认本地时区 `06:00`，可自定义）
   - `关闭定时，只在我手动提出时同步`
3. **规则体积预算档位**：
   - `(Recommended) 标准档：16 KB 警告 / 24 KB 硬上限（适配原生 Antigravity 24 KB 截断线）`
   - `扩展档：40 KB / 160 KB（仅限已自行解除 IDE 上限的用户）`
4. **已有全局 `GEMINI.md` / `AGENTS.md` 处理** *(仅 `doctor` 探测到非空原件时才问)*：
   - `(Recommended) 翻译拆解迁入新四类记忆库（先出保留/舍弃裁决表给你拍板，原件先备份）`
   - `保留原规则正文不变，仅在其后追加新索引与规程`
5. **当前工作区已有 `GEMINI.md` / `AGENTS.md` 处理** *(仅当前工作区存在外来规则文件时才问)*：
   - `(Recommended) 翻译迁入项目记忆库（先出裁决清单确认）`
   - `保留原 AGENTS.md 不接管（设 manage_agents=false，只新增 GEMINI.md 索引）`
   - `整目录忽略（ws ignore）`
6. **预生成本机工具速查正本（`memories/local-installed-tools.md`）** *(若已有或迁移过可跳过)*：
   - `(Recommended) 用 doctor 探测到的 PATH 开发工具先行生成 local-installed-tools.md（sync: auto），开局即可给全局 AGENTS.md 第四节供速查`
   - `暂不预生成（后续安装软件或踩到系统坑时再由 Agent 自动汇总建档）`
7. **上下文占用自动注入 Hook** *(可选开启，防止长任务压缩前遗漏未落盘规则)*：
   - `(Recommended) 仅高水位提醒：80% 以下完全静默，>=80% 时注入抢救提醒（每 3 次模型调用最多 1 次，>=92% 危急破例 1 次）`（`mode="threshold"`、`warn_percent=80`、`cooldown_calls=3`、`critical_percent=92`）
   - `全程注入精简占用，并在 >=80% 时附带记忆抢救提醒`（`mode="always"`）
   - `暂不安装 Hook`
8. **跨端分发** *(仅选双层模式且本机探测到 `~/.codex` / `~/.claude` 时才问)*：
   - 勾选需要在更新全局快照后自动同步覆盖的外部工具。

### 第 3 步 · 先迁旧规则再落盘（如选了翻译迁入）

1. 先完整读取原有 `GEMINI.md` / `AGENTS.md`，一字不改。
2. 输出**「保留（作用域 + 四类归属 + 目标文件名 + 理由）vs 舍弃（原因）」裁决清单**，等用户确认后再写正文。

### 第 4 步 · 写入脚本、配置、模板并跑通首轮校验

1. 复制 `./scripts/memsync.py` 到 `~/.gemini/memory-ops/memsync.py`（若开启上下文 Hook，同步复制 `./scripts/context_hook.py` 到 `~/.gemini/memory-ops/context_hook.py`）；复制 `./references/architecture.zh-CN.md`（或英文版）到 `~/.gemini/memory-ops/DESIGN.md`。
2. 运行 `bootstrap` 生成 `config.json` 与目录结构（后续若直接套完整模板写入全局 `GEMINI.md`，加 `--no-global-files`；开启 Hook 时直接传入 `--context-hook on --hook-mode <always|threshold> --hook-warn 80`）：
   ```bash
   <PYTHON_CMD> ~/.gemini/memory-ops/memsync.py bootstrap \
     --lang <zh|en> \
     --agents-cache <on|off> \
     --schedule <on|off> \
     --schedule-time <HH:MM> \
     --timezone <IANA_TZ> \
     --profile <standard|extended> \
     --context-hook <on|off> \
     --hook-mode <always|threshold> \
     --no-global-files
   ```
   有勾选外部工具时附带 `--target name=path`。传入 `--context-hook on`（或后续手动执行 `<PYTHON_CMD> ~/.gemini/memory-ops/memsync.py hook install`）会自动生成 `~/.gemini/config/plugins/milkfrog-context-hook/`（含 `plugin.json` 和适配各系统引号的 `hooks.json`），无需手改 JSON。
3. 写入全局 `~/.gemini/GEMINI.md`：写入前若存在原件先备份进 `~/.gemini/memory-ops/backup/`；套用 `templates/zh/global-gemini.full.md` 或 `.index-only.md`（替换 `{{MEMORY_HOME}}`、`{{OPS_DIR}}`、`{{PYTHON_CMD}}`、`{{BUDGET_PROFILE}}`），并写入已确认迁入的记忆正文与单行索引。若用户选择预生成工具清单，则把 `detected_toolchains` 核实到的 SDK/包管与用户确认的镜像/代理写进 `~/.gemini/memories/local-installed-tools.md`（`type: reference`、`scope: global`、`sync: auto`）并加入索引（密钥指针另建 `sync: never` 文件，绝不混写）。
4. 若开启双层模式：生成 `~/.gemini/memory-ops/RUNBOOK.md`；如已有记忆正文，跑一遍 `sync-plan -> global-input -> draft -> apply --scope global` 生成首份全局快照，否则写初始骨架。
5. 如用户要同时初始化当前打开的工作区 `<cwd>`：运行 `init "<cwd>" --summary "<定位>"`（保留原件则加 `--no-manage-agents`），写入项目记忆并用同样流程生成工作区 `AGENTS.md`。
6. 若用户开启了定时同步（`schedule_enabled=true`）：
   - 按 `templates/shared/sidecar-schedule.json` 生成 `~/.gemini/config/sidecars/daily-agents-memory-sync/sidecar.json`（填入真实 `CRON_TZ`、时间、已验证的 `<PYTHON_CMD>` 与工作区 `workspace_uris`；每次跑完会直接向用户输出含触发源与改动要点的简要汇报）。
   - **严禁代改 `user_config.json` 静默开启定时任务**。告诉用户到 `[Open Automations Dashboard](sidecar://dashboard)` 手动启用 **Daily Memory Snapshot Sync**，并主动询问是否先试跑一轮配置好权限白名单。

---

## 硬约束

- **装完即脱离 Skill**：日常行为规则必须全部留在 `~/.gemini/GEMINI.md` 头部，不能把日常执行步骤甩回 Skill 目录。
- **覆写必先备份**：动任何已有 `GEMINI.md`、`AGENTS.md` 或跨端目标文件前必须留一份备份在 `~/.gemini/memory-ops/backup/`。
- **绝不存明文凭据**：密钥或服务器密码只写指针且标 `sync: never`；git 仓必须忽略 `.gemini/memories/`。
- **不假设 `uv`**：统一使用第 1 步实测通过的 Python 命令。

---

## 模板与参考资料

- 架构设计与取舍：[architecture.zh-CN.md](./references/architecture.zh-CN.md) | [architecture.md](./references/architecture.md)
- 配置字段与 CLI 手册：[schema-and-config.zh-CN.md](./references/schema-and-config.zh-CN.md) | [schema-and-config.md](./references/schema-and-config.md)
- 排障与模式切换：[troubleshooting.zh-CN.md](./references/troubleshooting.zh-CN.md) | [troubleshooting.md](./references/troubleshooting.md)
- 模板目录：`templates/zh/` 与 `templates/en/`、`templates/shared/`
- 「程序员奶蛙」脱敏完整示例库：[examples/milkfrog-demo/](./examples/milkfrog-demo/)

---

## 自检与收尾

1. 运行 `lint` 并读取生成的 `work/lint-<today>.md` 报告，确认 `errors=0`：
   ```bash
   <PYTHON_CMD> ~/.gemini/memory-ops/memsync.py lint
   ```
2. 若开启双层模式，再跑一次 `sync-plan` 确认状态干净无异常漂移。
3. 清晰交代给用户：新建/改动了哪些文件、备份在哪里、当前开关状态位是什么（若安装了上下文 Hook，给出 `[milkfrog-context-hook](customization://milkfrog-context-hook)` 开关入口，告知自下轮用户对话起生效，且可用 `memsync.py hook uninstall` 随时卸载），并告知**日常已经完全由 `GEMINI.md` 接管，本 Skill 可以随时移除或停用**。

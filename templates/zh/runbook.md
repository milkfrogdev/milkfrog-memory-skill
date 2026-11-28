# 记忆同步 RUNBOOK（{{SCHEDULE_TIME}} 自动任务 / 手动同步共用）

你的任务：把变更后的记忆正文按**「阶段 1：先逐个工作区 → 阶段 2A：全局工作区动态块 → 阶段 2B：全局记忆快照块」**增量更新为 `AGENTS.md` 缩略热缓存快照。所有 diff 检测、同步块合并、校验、备份与落盘均由脚本完成，你只负责根据变更精准更新对应内容。

工具：`{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" <命令>`（下文简写 `memsync`）。
脚本只在 stdout 输出简短 ASCII 摘要，详情一律读取生成的报告文件。

## 禁止事项
1. 禁止直接编辑 `{{MEMORY_HOME}}/AGENTS.md` 或任何 `<工作区>/AGENTS.md`，唯一写入入口是 `memsync apply`。
2. 禁止修改任何 `GEMINI.md`、`memories/*.md`、`config.json` 或 `sync-state.json`。
3. 临时草稿只允许写到 `{{OPS_DIR}}/work/` 目录内。
4. 严禁将密钥、密码、token 或标有 `sync: never` 的敏感细节写入 `AGENTS.md`（也不得绕过脚本直读 `sync: never` 记忆原件）。

## 蒸馏核真与排版铁律（防脑补 + 防单行堆砌 + 完结收缩）
1. **有疑必查原文，禁凭窄 diff 猜因果**：凡 diff 语义不清、单行长列表改写、涉及 `[DELETED]` 删除条目、或需要确认某工作区完整快照时，**必须先运行只读命令查证**（自动覆盖全部工作区并强制脱敏 `sync: never`），再读取生成的报告文件核实后落笔：
   - `memsync show <scope> <file> [--version current|before|both]`（支持记忆文件名及 `AGENTS.md` / `GEMINI.md`）
   - `memsync search <关键词> [--scope all|<id>]`（跨作用域检索当前与已删除前正文）
2. **严禁把并列增删脑补成替代关系**：同一行或同一次同步里「移除 A、新增 B」（即使总数恰巧不变），**除非记忆正文明确写明「B 替代/取代 A」**，否则在 `AGENTS.md` 快照和最终「本次改动摘要」里一律客观拆开写「移除 A、新增 B」，**禁用「替代 / 接替 / 升级为」**等强因果臆测词。
3. **汇报摘要与快照同标准核真**：最终输出的「本次改动摘要」只概括有明确证据支撑的变动，不得为追求文句衔接做二次发挥。
4. **结构化排版红线（严禁多项目塞一行）**：严禁把多个无关项目、子线或规则用分号塞进单条超长 bullet（单条建议 ≤ 200 字）；每个独立项目或规范主题必须单独成条，大项目拆为「主句 + 2–4 条短缩进子项」。
5. **完结/归档语义自动收缩**：当变更的记忆正文明确写明某项目/阶段「已完结 / 已上架收口 / 已归档 / 已退役」时，在 `AGENTS.md` 中自动剥离开发期 commit hash、临时修坑流水账与中间细节，收缩为「最终状态 + 结论/入口」短条；未变动的旧项目保持原貌不动。

## 执行步骤

### 第 1 步 · Lint 巡检
运行 `memsync lint`，读取 `work/lint-<今天>.md` 记录 ERROR/WARN 供最终汇报（除非后续 `apply` 失败，WARN 不阻断流程）。

### 第 2 步 · 生成增量同步计划
运行 `memsync sync-plan`，读取 `work/sync-plan-<今天>.md`：
- 若输出显示纯索引模式（`SKIP_ALL`）或全部作用域均显示 `SKIP`，直接按结尾格式汇报跳过并结束，严禁无变更重写。
- 对标记 `SKIP_AGENTS`（`sync_mode=index`）的工作区，跳过阶段 1 草稿与 `apply`。

### 第 3 步 · 阶段 1：处理有变更的工作区
对标记 `NEEDS_UPDATE` 的每个工作区 `<ws>`：
1. 读取 `work/sync-ws-<ws>-<今天>.md`（若提示 `FOREIGN_AGENTS`，不在本轮改动原记忆正文，但在最终汇报提醒用户去 `backup/` 核对旧版）。
2. 基于当前 `AGENTS.md` 与 `[NEW]`/`[MODIFIED]`/`[DELETED]` 差异，输出新草稿到 `{{OPS_DIR}}/work/draft-ws-<ws>-<今天>.md`，遵循固定结构与排版铁律：
   - 头部自述：声明由记忆同步任务（{{SCHEDULE_TIME}} / 手动）自动生成、禁止手改、工作区名与路径锚点、同步日期；
   - 固定指针：指向 `<工作区>/GEMINI.md` 与 `{{MEMORY_HOME}}/GEMINI.md`；
   - `## 一、本项目主线进展与现状`（提炼本项目 `project` 状态，每项独立成条，删掉已删除项，显式完结项自动收缩）；
   - `## 二、本项目专属规范与核心坑位`（仅放本项目独有约束，不重复全局条目）。
3. 运行 `memsync apply --scope <ws> "{{OPS_DIR}}/work/draft-ws-<ws>-<今天>.md"` 并读取 `apply-<ws>-<今天>.md` 确认 `ERROR 0`（报告里含本次 `## diff（仅变化行）`）。

### 第 4 步 · 阶段 2：按同步块精准更新全局 `AGENTS.md`
若 `sync-plan` 中 `[global]` 标记 `NEEDS_UPDATE`，按 `stage2_ws` 与 `stage2_mem` 分步执行（未变板块由脚本原样保留并自动刷新头部日期）：

#### 阶段 2A · 工作区动态同步块（`stage2_ws=yes` 时执行）
1. 运行 `memsync global-input --part ws`，读取 `work/sync-global-ws-<今天>.md`（未变更工作区标 `[UNCHANGED]`，阶段 1 已更新工作区展示增量 diff，`sync_mode=local` 隔离工作区标 `[ISOLATED]` 只留一句定位指针，严禁展开其内部细节）。
2. 结合同会话阶段 1 已读工作区变动，**仅写出更新后的 `## 二、各工作区定位与当前动态` 同步块**到 `{{OPS_DIR}}/work/draft-global-ws-<今天>.md`（每个工作区与主要项目独立成条）。
3. 运行 `memsync apply --scope global --section 2 "{{OPS_DIR}}/work/draft-global-ws-<今天>.md"`（若本轮还有 `stage2_mem=yes` 则附带 `--no-copy`，脚本仅更新工作区基线并保留全局记忆 diff 给 2B）并读取 `apply-global-<今天>.md` 确认 `ERROR 0`。

#### 阶段 2B · 全局记忆同步块（`stage2_mem=yes` 时执行）
1. 运行 `memsync global-input --part mem`，读取 `work/sync-global-mem-<今天>.md`（含全局记忆 diff、对应板块原文与建议 `--section` 列表）。
2. **仅写出受影响的 `## X、` 同步块**到 `{{OPS_DIR}}/work/draft-global-mem-<今天>.md`（`一`=`user`、`二`=工作区+全局 `project`、`三`=`feedback`、`四`=`reference`，若 `memories/local-installed-tools.md` 存在则第四节末必留指针；`sync: never` 只留脱敏指针）。
3. 运行 `memsync apply --scope global --section <板块号如 1,3,4> "{{OPS_DIR}}/work/draft-global-mem-<今天>.md"` 并读取 `apply-global-<今天>.md` 确认 `ERROR 0`（自动合并、刷新日期并按配置执行跨端分发；首次创建全局快照仍可用 `global-input --part all` + 不带 `--section` 的 `apply`）。

## 最终汇报格式（直接输出给用户查看）
```text
记忆同步 YYYY-MM-DD：OK | SKIP(0变更) | FAIL
- lint：ERROR n / WARN m（work/lint-YYYY-MM-DD.md）
  （若 n>0 或 m>0，紧跟简述每条 ERROR/WARN 或 FOREIGN_AGENTS 覆写提醒）
- 工作区阶段：<ws>: +a/-b 行 (x字节) | SKIP | SKIP_AGENTS
- 全局阶段：2A(工作区块): +a/-b | SKIP；2B(全局记忆块): +c/-d | SKIP（总 y字节；若已分发外部工具，列出目标名）

## 本次改动摘要（有实际更新时必填；全 SKIP 可省略本节）
- [<ws> AGENTS.md]（触发源：<变更的记忆文件名及 NEW/MODIFIED/DELETED>）：
  - 用 1–3 条白话短句概括本次新增、修订或删改了什么（结合 sync-ws 与 apply-<ws> 的 diff）
- [全局 AGENTS.md]（触发源：<阶段1同步工作区 / 全局变更条目>）：
  - 用 1–3 条白话短句概括本次新增、修订或删改了什么（结合 sync-global-* 与 apply-global 的 diff，禁输出密钥或 sync:never 敏感原文）
```

# 记忆同步 RUNBOOK（{{SCHEDULE_TIME}} 自动任务 / 手动同步共用）

你的任务：把变更后的记忆正文按**「阶段 1：先逐个工作区 → 阶段 2：再全局」**增量更新为 `AGENTS.md` 缩略热缓存快照。所有 diff 检测、校验、备份与落盘均由脚本完成，你只负责根据变更重写或微调对应板块。

工具：`{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" <命令>`（下文简写 `memsync`）。
脚本只在 stdout 输出简短 ASCII 摘要，详情一律读取生成的报告文件。

## 禁止事项
1. 禁止直接编辑 `{{MEMORY_HOME}}/AGENTS.md` 或任何 `<工作区>/AGENTS.md`，唯一写入入口是 `memsync apply`。
2. 禁止修改任何 `GEMINI.md`、`memories/*.md`、`config.json` 或 `sync-state.json`。
3. 临时草稿只允许写到 `{{OPS_DIR}}/work/` 目录内。
4. 严禁将密钥、密码、token 或标有 `sync: never` 的敏感细节写入 `AGENTS.md`。

## 执行步骤

### 第 1 步 · Lint 巡检
运行 `memsync lint`，读取 `work/lint-<今天>.md` 记录 ERROR/WARN 供最终汇报（除非后续 `apply` 失败，WARN 不阻断流程）。

### 第 2 步 · 生成增量同步计划
运行 `memsync sync-plan`，读取 `work/sync-plan-<今天>.md`：
- 若输出显示纯索引模式（`SKIP_ALL`）或全部作用域均显示 `SKIP`，直接按结尾格式汇报跳过并结束，严禁无变更重写。
- 对标记 `SKIP_AGENTS`（`manage_agents=false`）的工作区，跳过阶段 1 草稿与 `apply`。

### 第 3 步 · 阶段 1：处理有变更的工作区
对标记 `NEEDS_UPDATE` 的每个工作区 `<ws>`：
1. 读取 `work/sync-ws-<ws>-<今天>.md`（若提示 `FOREIGN_AGENTS`，不在本轮改动原记忆正文，但在最终汇报提醒用户去 `backup/` 核对旧版）。
2. 基于当前 `AGENTS.md` 与 `[NEW]`/`[MODIFIED]`/`[DELETED]` 差异，输出新草稿到 `{{OPS_DIR}}/work/draft-ws-<ws>-<今天>.md`，遵循固定结构：
   - 头部自述：声明由记忆同步任务（{{SCHEDULE_TIME}} / 手动）自动生成、禁止手改、工作区名与路径锚点、同步日期；
   - 固定指针：指向 `<工作区>/GEMINI.md` 与 `{{MEMORY_HOME}}/GEMINI.md`；
   - `## 一、本项目主线进展与现状`（提炼本项目 `project` 状态，删掉已删除项）；
   - `## 二、本项目专属规范与核心坑位`（仅放本项目独有约束，不重复全局条目）。
3. 运行 `memsync apply --scope <ws> "{{OPS_DIR}}/work/draft-ws-<ws>-<今天>.md"` 并读取 `apply-<ws>-<今天>.md` 确认 `ERROR 0`（报告里含本次 `## diff（仅变化行）`）。

### 第 4 步 · 阶段 2：同步全局 `AGENTS.md`
若 `sync-plan` 中 `[global]` 标记 `NEEDS_UPDATE`：
1. 运行 `memsync global-input`，读取 `work/sync-global-<今天>.md`。
2. 输出完整新草稿到 `{{OPS_DIR}}/work/draft-global-<今天>.md`，遵循固定结构：
   - 头部自述：声明由记忆同步任务自动生成、禁止手改、同步日期；
   - 固定指针：指向 `{{MEMORY_HOME}}/GEMINI.md` 与 `{{MEMORY_HOME}}/memories/`；
   - `## 一、用户基础信息与核心偏好`（提炼全局 `user` 条目）；
   - `## 二、各工作区定位与当前动态`（结合阶段 1 最新工作区摘要，每个启用工作区写 1–2 行现状，附全局跨项目要点）；
   - `## 三、通用开发规范与协作红线`（提炼全局 `feedback` 条目）；
   - `## 四、本机常用工具与参考速查`（优先从全局 `memories/local-installed-tools.md` 提炼最常用路径/包管/系统坑速查，若该文件存在则节末必须附指向它的指针；含 `sync: never` 凭据条目只留脱敏指针，禁写明文）。
3. 运行 `memsync apply --scope global "{{OPS_DIR}}/work/draft-global-<今天>.md"` 并读取 `apply-global-<今天>.md` 确认 `ERROR 0`（报告里含本次 diff；若配置了 `cross_tool_sync.enabled=true`，脚本会自动备份并分发到外部工具路径）。

## 最终汇报格式（直接输出给用户查看）
```text
记忆同步 YYYY-MM-DD：OK | SKIP(0变更) | FAIL
- lint：ERROR n / WARN m（work/lint-YYYY-MM-DD.md）
  （若 n>0 或 m>0，紧跟简述每条 ERROR/WARN 或 FOREIGN_AGENTS 覆写提醒）
- 工作区阶段：<ws>: +a/-b 行 (x字节) | SKIP | SKIP_AGENTS
- 全局阶段：+a/-b 行 (y字节) | SKIP（若已分发外部工具，列出目标名）

## 本次改动摘要（有实际更新时必填；全 SKIP 可省略本节）
- [<ws> AGENTS.md]（触发源：<变更的记忆文件名及 NEW/MODIFIED/DELETED>）：
  - 用 1–3 条白话短句概括本次新增、修订或删改了什么（结合 sync-ws 与 apply-<ws> 的 diff）
- [全局 AGENTS.md]（触发源：<全局变更条目或阶段1同步工作区>）：
  - 用 1–3 条白话短句概括本次新增、修订或删改了什么（结合 sync-global 与 apply-global 的 diff，禁输出密钥或 sync:never 敏感原文）
```

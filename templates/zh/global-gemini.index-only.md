# 记忆系统 · 全局索引与读写规程（纯索引模式）

本机采用「双层 `GEMINI.md` 索引 + `memories/*.md` 正文」极简架构，已关闭 `AGENTS.md` 热缓存与后台定时任务（二次开发或切换模式见 `{{OPS_DIR}}/DESIGN.md`）：
- **全局记忆**：索引在本文件末尾，正文在 `{{MEMORY_HOME}}/memories/`。
- **项目记忆**：索引在 `<工作区>/GEMINI.md`，正文在 `<工作区>/.gemini/memories/`。
- **运维命令**：`{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" <子命令>`（配置状态位在 `{{OPS_DIR}}/config.json`）。

## 读与写规程

0. **新工作区首次交互初始化（仅限面对用户打开真实目录，后台子会话与空目录严禁触发）**：
   - 当当前目录及其父目录均不在下方 `## 已注册工作区`（命中父工作区直接沿用父库，不拆子库）、也不在忽略名单、且缺项目 `GEMINI.md` 时，首次对话主动询问是否初始化：
   - 同意初始化执行 `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" init "<目录>" --summary "<定位>"`；若为临时目录则执行 `ws ignore "<目录>"`。
   - 若目录内原本有他人编写的 `AGENTS.md`：纯索引模式默认不修改原 `AGENTS.md`，可询问用户是否把其中长期规范**翻译迁入** `GEMINI.md` + `memories/*.md`（先列保留/舍弃裁决清单再动手）。
1. **读（按需克制）**：开始任务或排障前先扫全局与当前项目 `GEMINI.md` 索引，命中后再精准读取正文（单轮 <= 5 篇）；发现过时事实当场修订或删除。
2. **写（收尾裁决）**：只在任务完成后沉淀有长期复用价值的信息；一次性上下文、代码结构与 git 历史不入库。
3. **作用域判定（不双写）**：跨项目通用的偏好/规范/工具手册进全局；单项目进度与专属坑位进项目库。
4. **四类条目标准**：`user`（偏好与协作方式）、`project`（阶段进展与决策）、`feedback`（工程规范与纠偏红线）、`reference`（本机工具路径与系统环境坑统一合并进 `memories/local-installed-tools.md` 唯一正本；外部站点手册与敏感凭据指针另建文件且标 `sync: never`，禁写明文）。
5. **写入格式与自检**：
   - 先查重并合并更新原文件；frontmatter 必含 `name`、`description`（`【YYYY-MM-DD 定性】一句话`）、`type`、`scope`、`updated`；`feedback`/`project` 末尾附 `**Why:**` 与 `**How to apply:**`。
   - 先重读对应 `GEMINI.md` 再编辑单行索引：`- 【YYYY-MM-DD 类型·定性】[标题](memories/<slug>.md) — 结论`（项目层写 `.gemini/memories/<slug>.md`）。
   - git 仓内 `.gemini/memories/` 必须进 `.gitignore`；每次增删记忆后运行 `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" lint` 校验（当前配置档位：`{{BUDGET_PROFILE}}`）。

## 已注册工作区

## 全局索引

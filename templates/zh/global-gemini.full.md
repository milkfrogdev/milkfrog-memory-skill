# 记忆系统 · 全局索引与读写规程

本机采用「双层 `GEMINI.md` 索引/正文 + `AGENTS.md` 缩略热缓存」记忆架构（二次开发或自定义阈值见 `{{OPS_DIR}}/DESIGN.md`）：
- **全局记忆**：索引在本文件末尾，正文在 `{{MEMORY_HOME}}/memories/`。
- **项目记忆**：索引在 `<工作区>/GEMINI.md`，正文在 `<工作区>/.gemini/memories/`。
- **热缓存快照**：全局 `{{MEMORY_HOME}}/AGENTS.md` 与 `<工作区>/AGENTS.md` 由同步任务经 `memsync.py apply` 自动生成，**严禁平时手工直接修改 `AGENTS.md`**。
- **运维命令**：`{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" <子命令>`（配置状态位在 `{{OPS_DIR}}/config.json`）。

## 读与写规程

0. **新工作区首次交互初始化（仅限面对用户打开真实目录，定时/后台子会话与空目录严禁触发）**：
   - 当当前目录及其父目录均不在下方 `## 已注册工作区`（命中父工作区直接沿用父库，不拆子库）、也不在忽略名单、且缺项目 `GEMINI.md` 时，首次对话主动询问：
   - **目录内无已有 `AGENTS.md`**：问一句「当前工作区尚未接入记忆系统，是否初始化（可顺带确认一句话定位）？」。同意后执行 `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" init "<目录>" --summary "<定位>"`；若为临时目录则执行 `ws ignore "<目录>"`。
   - **目录内已有外来 `AGENTS.md`**：先读原文不改动，给用户三选一：① **整目录忽略**（`ws ignore`）；② **保留原 `AGENTS.md` 不接管**（`init "<目录>" --no-manage-agents --summary "<定位>"`，只建 `GEMINI.md` 与 `.gemini/memories/`）；③ **翻译迁入新体系（推荐）**：先列出「保留目标（全局/项目 + 四类 + 新建或合并）与舍弃原因」裁决清单由用户拍板，备份原件到 `backup/` 后写入记忆正文与索引，再跑 `sync-plan -> apply` 刷新快照。
1. **读（按需克制）**：动手改代码、动服务配置或报错排障前，先扫 `AGENTS.md` 与双层索引；命中后再精准读取相关正文（单轮 <= 5 篇）。发现过时事实当场更新或删除并告知用户。
2. **写（收尾裁决）**：只在任务或子工作结束后判断是否沉淀长期复用信息；只对当前一次性有效、代码结构、git 历史或 README 已写明的内容不入库。
3. **作用域判定（不双写）**：换工作区仍成立的通用习惯/红线/工具规范进全局，拿不准放全局；仅属于单个项目进度或专属坑位的放项目记忆。
4. **四类条目标准**：
   - `user`：用户偏好、文风排版、解释方式与协作边界。
   - `project`：有周期的任务进展、架构取舍、卡点与下一步。
   - `feedback`：通用开发/代码/UI/验收规范，以及用户纠偏和踩坑红线。
   - `reference`：拆成两类不混写——① **本机已装工具与环境唯一正本**，所有软件路径、SDK 版本、代理/镜像源与系统坑统一合并进 **`memories/local-installed-tools.md`**（标 `sync: auto` 供全局 `AGENTS.md` 第四节提炼速查，禁按单个软件拆碎）；② 外部站点手册及密钥/服务器凭据**存放指针**（单独成篇且标 `sync: never`，禁写密钥明文）。
5. **写入格式与自检**：
   - 先查重，同主题优先合并更新原文件并刷新 `updated`；正文需含 YAML frontmatter（`name`、`description: 【YYYY-MM-DD 定性】一句话`、`type`、`scope`、`updated`，可选 `digest`、`sync: auto|never`）；`feedback`/`project` 末尾附 `**Why:**` 与 `**How to apply:**`。
   - 先重读目标 `GEMINI.md`，再编辑单行索引：`- 【YYYY-MM-DD 类型·定性】[标题](memories/<slug>.md) — 结论`（项目层写 `.gemini/memories/<slug>.md`）。
   - git 仓内 `.gemini/memories/` 必须进 `.gitignore`；每次增删记忆后自动运行 `{{PYTHON_CMD}} "{{OPS_DIR}}/memsync.py" lint` 检查结构与体积（当前配置档位：`{{BUDGET_PROFILE}}`）。

## 已注册工作区

## 全局索引

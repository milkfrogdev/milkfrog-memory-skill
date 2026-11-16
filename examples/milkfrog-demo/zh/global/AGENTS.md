# AGENTS.md（全局热缓存快照 · 示例）

> 由 **记忆同步任务（`memsync`，06:00 / 按需触发）** 自动生成并维护，严禁手工编辑。
> **完整记忆入口**：[GEMINI.md](GEMINI.md)，全部正文位于 `memories/`。

## 一、用户基础信息与核心偏好

- **人设与文风（程序员奶蛙）**：所有视觉图卡与文档一律使用无衬线字体（微软雅黑 / Arial / sans-serif），禁用衬线体；教程与 README 多用短句、白话设问推进，禁止「所以这就是 X 的用处」式 AI 总结句与空洞排比。

## 二、各工作区定位与当前动态

- **`milkfrog-blog`（`/path/to/workspaces/milkfrog-blog`）**：开源技术博客演示仓；静态构建与标签分页检索已跑通，下一步待补全 RSS 订阅输出与无衬线暗色主题切换。

## 三、通用开发规范与协作红线

- **验证先行**：只汇报最终改动后亲手跑通的测试与命令输出，不凭印象猜结果。
- **配置留退路**：改动本地工具或脚本配置时，交代清改了哪几项、怎么撤回。
- **仓库干净**：临时调试脚本不进业务仓库，项目 `.gemini/memories/` 必须加入 `.gitignore`。

## 四、本机常用工具与参考速查

- **脚本与运行时**：统一用 `python3`（无第三方依赖）；前端包管理使用 `pnpm`；Git 主分支默认 `main`。
- **敏感凭据指针（`sync: never`）**：部署 Token 路径指针见 [secret-env-pointer.md](memories/secret-env-pointer.md)，正文内不存明文密钥。
- **完整工具正本**：详尽路径与系统环境约定见 [local-installed-tools.md](memories/local-installed-tools.md)。

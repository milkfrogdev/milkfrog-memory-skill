---
name: blog-rss-roadmap
description: 【2026-11-16 项目·示例】奶蛙开源博客站点当前状态与下一步里程碑
digest: 标签筛选与静态构建已完成；待补 Atom/RSS 输出与暗色主题开关
metadata:
  type: project
  scope: project
  created: 2026-11-16
  updated: 2026-11-16
  sync: auto
---

# 奶蛙博客演示项目进展（示例）

- **已完成**：静态构建链路、Markdown Frontmatter 解析、按标签筛选和每页 10 篇分页。
- **技术取舍**：搜索索引直接随构建产物生成一份轻量 JSON，不引入后端搜索引擎，保持纯静态托管。
- **下一步**：补充 `/rss.xml` 生成脚本，并把主题切换开关做成无闪烁系统默认 + 手动覆盖（字体坚持无衬线）。

**Why:** 个人技术博客优先低运维、纯静态部署，避免为少量文章维护数据库。
**How to apply:** 在 `milkfrog-blog` 新增功能前先检查静态 JSON 索引大小和 RSS XML 校验单测。

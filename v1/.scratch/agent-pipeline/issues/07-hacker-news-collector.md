# 07 — Hacker News 采集器

**What to build:** 扩展 collector Agent，支持从 Hacker News 抓取 AI 相关内容，保存到 `knowledge/raw/` 目录。

**Blocked by:** 02 — GitHub Trending 采集器, 06 — LangGraph 工作流编排

**Status:** ready-for-agent

- [ ] 实现 `utils/hackernews_api.py`，调用 HN API（https://hacker-news.firebaseio.com）
- [ ] 抓取 Top Stories，过滤 AI 相关内容（基于标题、URL）
- [ ] 提取故事信息（标题、URL、分数、评论数）
- [ ] 保存为 JSON 格式到 `knowledge/raw/hackernews-{date}.json`
- [ ] 更新 workflow/pipeline.py，支持多数据源采集
- [ ] 添加单元测试，mock HN API 请求
- [ ] 验证：运行采集后 `knowledge/raw/` 目录生成 HN 数据文件
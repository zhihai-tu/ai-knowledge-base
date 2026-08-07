# 02 — GitHub Trending 采集器

**What to build:** 实现 collector Agent 的核心功能，能够抓取 GitHub Trending 页面，提取 AI 相关项目，保存到 `knowledge/raw/` 目录。

**Blocked by:** 01 — 基础设施搭建

**Status:** ready-for-agent

- [ ] 实现 `utils/github_trending.py`，使用 httpx 抓取 GitHub Trending 页面
- [ ] 解析 HTML 提取项目信息（名称、URL、描述、星标数、语言）
- [ ] 实现 AI 相关项目过滤逻辑（基于关键词、语言、描述）
- [ ] 支持配置抓取数量（默认 Top 50）
- [ ] 保存为 JSON 格式到 `knowledge/raw/github-trending-{date}.json`
- [ ] 添加单元测试，mock HTTP 请求
- [ ] 验证：运行采集后 `knowledge/raw/` 目录生成新文件
---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending 采集技能

## 使用场景

当需要从 GitHub Trending 页面采集当前热门开源项目，特别是 AI/LLM/Agent 相关的技术动态时，使用此技能。

## 执行步骤

### 步骤 1：搜索热门仓库

通过 GitHub API 获取当前热门仓库：

```
GET https://api.github.com/search/repositories?q=created:>YYYY-MM-DD&sort=stars&order=desc&per_page=100
```

其中 `YYYY-MM-DD` 为 7 天前的日期。

### 步骤 2：提取信息

从 API 响应中提取每个仓库的关键信息：
- `name`：仓库全名（owner/repo）
- `html_url`：仓库链接
- `description`：项目描述
- `stargazers_count`：Star 数量
- `language`：主要编程语言
- `topics`：主题标签

### 步骤 3：过滤

**纳入条件**（满足任一）：
- topics 包含：`llm`, `ai`, `machine-learning`, `deep-learning`, `agent`, `rag`, `embedding`, `chatbot`, `nlp`, `transformer`
- description 包含关键词：`LLM`, `AI agent`, `language model`, `RAG`, `embedding`

**排除条件**（满足任一）：
- 仓库名包含 `awesome` 或 `awesome-`
- description 包含 `curated list`, `collection of`, `resources list`
- stars < 100（新项目可适当放宽）

### 步骤 4：去重

按仓库名去重，确保同一项目不重复收录。

### 步骤 5：撰写中文摘要

为每个项目撰写 100-200 字的中文摘要，遵循公式：

> **项目名 + 做什么 + 为什么值得关注**

摘要应包含：
- 项目的核心功能
- 技术亮点或创新点
- 适用场景
- 社区活跃度（Star 增长、贡献者数量等）

### 步骤 6：排序取 Top15

按以下权重综合排序：
- Star 数量（40%）
- 近 7 天增长趋势（40%）
- 与 AI/LLM/Agent 的相关性（20%）

取前 15 个项目。

### 步骤 7：输出 JSON

将结果保存到 `knowledge/raw/github-trending-YYYY-MM-DD.json`，其中 `YYYY-MM-DD` 为当天日期。

## 注意事项

- API 请求需携带 `Accept: application/vnd.github.v3+json` 头部
- GitHub API 未认证限制为每小时 60 次请求，建议添加 Token
- 摘要必须使用中文，避免直接翻译英文描述
- 日期格式统一使用 ISO 8601（`2026-07-09T10:00:00Z`）
- 文件名中的日期使用采集当天的日期

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-07-09T10:00:00Z",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "这是一个 XXX 项目，主要功能是...值得关注的原因是...",
      "stars": 15000,
      "language": "Python",
      "topics": ["llm", "agent"]
    }
  ]
}
```

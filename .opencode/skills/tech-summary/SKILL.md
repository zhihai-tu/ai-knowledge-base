---
name: tech-summary
description: 当需要对采集的技术内容进行深度分析总结时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# 技术内容深度分析技能

## 使用场景

当需要对 `knowledge/raw/` 目录下已采集的技术内容（GitHub Trending、Hacker News 等）进行深度分析、评分和趋势总结时，使用此技能。

## 执行步骤

### 步骤 1：读取最新采集文件

1. 使用 Glob 扫描 `knowledge/raw/` 目录，查找最新的采集文件
2. 文件命名规则：`github-trending-YYYY-MM-DD.json` 或 `hacker-news-YYYY-MM-DD.json`
3. 使用 Read 读取文件内容，解析 JSON

### 步骤 2：逐条深度分析

对采集到的每个项目进行深度分析，输出以下字段：

| 字段 | 要求 |
|------|------|
| `summary` | ≤50 字中文摘要，说明项目核心价值 |
| `highlights` | 2-3 个技术亮点，必须用事实说话（具体数据、技术原理、对比优势） |
| `score` | 1-10 分评分，附简短理由 |
| `tags` | 建议标签，便于分类检索 |

**评分标准**：

| 分数区间 | 含义 | 说明 |
|----------|------|------|
| 9-10 | 改变格局 | 颠覆性创新，可能改变整个领域发展方向 |
| 7-8 | 直接有帮助 | 可立即用于实际项目，提升开发效率 |
| 5-6 | 值得了解 | 技术方案有参考价值，适合学习借鉴 |
| 1-4 | 可略过 | 意义不大或与当前方向相关性低 |

### 步骤 3：趋势发现

分析所有项目后，识别以下内容：

- **共同主题**：多个项目涉及的相同技术方向
- **新兴概念**：首次出现或关注度突然提升的技术术语
- **技术演进**：已有技术的新进展或变体

趋势总结控制在 200 字以内，用中文输出。

### 步骤 4：输出分析结果 JSON

将分析结果保存到 `knowledge/articles/tech-summary-YYYY-MM-DD.json`，其中 `YYYY-MM-DD` 为当天日期。

## 约束

- **评分分布**：15 个项目中，9-10 分不得超过 2 个
- **摘要字数**：每个项目的 `summary` 严格控制在 50 字以内
- **技术亮点**：必须基于事实，禁止主观臆断（如"非常强大"、"业界领先"）
- **输出格式**：严格遵循下方 JSON 结构，不得增减字段
- **语言要求**：所有分析内容使用中文

## 输出格式

```json
{
  "source": "tech-summary",
  "skill": "tech-summary",
  "analyzed_at": "2026-07-09T10:00:00Z",
  "source_file": "knowledge/raw/github-trending-2026-07-09.json",
  "trends": {
    "common_topics": ["多模态Agent", "本地化LLM推理"],
    "emerging_concepts": ["Mixture of Agents", "Speculative Decoding"],
    "summary": "本周技术动态显示..."
  },
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "一句话说明项目核心价值",
      "highlights": [
        "亮点1：具体事实或数据",
        "亮点2：技术原理或创新点",
        "亮点3：实际应用场景"
      ],
      "score": 8,
      "score_reason": "可直接用于生产环境的 RAG 框架，社区活跃",
      "tags": ["rag", "production-ready"]
    }
  ]
}
```

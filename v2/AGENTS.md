# AI 知识库助手 AGENTS.md

## 项目概述

本项目是一个自动化 AI 知识库助手，负责从 GitHub Trending 和 Hacker News 等渠道实时采集 AI/LLM/Agent 领域的技术动态，通过 AI 分析后结构化存储为 JSON 格式，并支持向 Telegram、飞书等多渠道分发。

## LLM 配置

- 统一由 `pipeline/model_client.py` 提供 LLM 调用（httpx 直连 OpenAI 兼容接口，不依赖 openai SDK）。
- 配置存于项目根目录 `.env`（模板见 `.env.example`），受 `.gitignore` 保护，禁止提交真实 Key。
- 优先级：进程环境变量 > `.env`。变量：`LLM_PROVIDER`（deepseek/qwen/openai，默认 deepseek）、`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、`OPENAI_API_KEY`。
- 新增模型价格需同步登记到 `MODEL_PRICES_USD`（USD / 1M tokens）。

本项目是一个自动化 AI 知识库助手，负责从 GitHub Trending 和 Hacker News 等渠道实时采集 AI/LLM/Agent 领域的技术动态，通过 AI 分析后结构化存储为 JSON 格式，并支持向 Telegram、飞书等多渠道分发。

## 知识条目 JSON 格式

```json
{
  "id": "gh-trending-20260709-001",
  "title": "项目名称",
  "source_url": "https://github.com/user/repo",
  "source_type": "github_trending | hacker_news",
  "summary": "详细的中文摘要（150-300字）",
  "tags": ["llm", "agent", "rag"],
  "category": "llm | agent | rag | inference | training | tool",
  "status": "raw | analyzed | published",
  "collected_at": "2026-07-09T10:00:00Z",
  "analyzed_at": null,
  "published_at": null,
  "distribution": {
    "telegram": false,
    "feishu": false
  },
  "metadata": {
    "stars": 15000,
    "language": "Python",
    "author": "username",
    "highlights": ["亮点1", "亮点2", "亮点3"],
    "score": 8,
    "score_reason": "评分理由"
  }
}
```


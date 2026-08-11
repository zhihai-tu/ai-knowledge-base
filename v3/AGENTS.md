# AI 知识库助手 AGENTS.md

## 项目概述

本项目是 V3 版本，基于 V2 代码骨架初始化。V2 是自动化 AI 知识库助手：从 GitHub Trending、RSS 等渠道实时采集 AI/LLM/Agent 领域技术动态，通过 AI 分析后结构化存储为 JSON 格式，并支持多渠道分发。V3 将在 V2 基础上引入多 Agent 能力（agent 架构待设计，本文件将随架构确定同步更新）。

## LLM 配置

- 统一由 `workflows/model_client.py`（`workflows.model_client`）提供 LLM 调用（httpx 直连 OpenAI 兼容接口，不依赖 openai SDK）。`pipeline/model_client.py` 仅为向后兼容的 re-export 层，新代码一律从 `workflows.model_client` 导入。
- 多 Agent 路由模块 `patterns/router.py` 提供 `route(query)` 统一入口：两层意图分类（关键词快速匹配 → LLM 兜底），分发给 github_search（GitHub Search API，`urllib.parse.quote` 编码查询参数）/ knowledge_query（扫描 `knowledge/articles/*.json` 关键词检索）/ general_chat（`quick_chat`）三个处理器。
- 配置存于项目根目录 `.env`（模板见 `.env.example`），受 `.gitignore` 保护，禁止提交真实 Key。
- 优先级：进程环境变量 > `.env`。变量：`LLM_PROVIDER`（deepseek/qwen/openai，默认 deepseek）、`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、`OPENAI_API_KEY`、`LOG_LEVEL`（DEBUG/INFO/WARNING/ERROR，默认 INFO）。qwen 提供商额外支持 `QWEN_BASE_URL`（百炼专属网关 OpenAI 兼容地址，覆盖默认公共版）与 `QWEN_MODEL`（模型名覆盖）。流水线支持 `--provider` 参数指定提供商（`pipeline.py` 传入 `create_provider(name=...)`）。
- 新增模型价格只登记到 `MODEL_PRICES_USD`（USD / 1M tokens）；成本统一按模型单价计算 USD，不做汇率换算（`CostTracker` 以 (provider, model) 键记录并输出 USD 报告）。

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


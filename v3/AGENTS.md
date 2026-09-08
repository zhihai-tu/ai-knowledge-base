# AI 知识库助手 AGENTS.md

## 项目概述

本项目是 V3 版本，基于 V2 代码骨架初始化。V2 是自动化 AI 知识库助手：从 GitHub Trending、RSS 等渠道实时采集 AI/LLM/Agent 领域技术动态，通过 AI 分析后结构化存储为 JSON 格式，并支持多渠道分发。V3 将在 V2 基础上引入多 Agent 能力（agent 架构待设计，本文件将随架构确定同步更新）。

> 通用设计原则「以简单为主，不要过度设计」见根目录 `AGENTS.md`，V1-V4 通用。

## LLM 配置

- `.env` 与 `.env.example` 的同名变量使用一致的通用注释，只解释字段用途及默认值规则；切换供应商时只修改配置值，不改写变量注释。
- Kimi Code 使用 `LLM_PROVIDER=kimi-code`、`LLM_BASE_URL=https://api.kimi.com/coding/v1`、`LLM_MODEL=kimi-for-coding`，由用户在 `LLM_API_KEY` 填写 Kimi Code 控制台密钥。沿用 OpenAI 兼容客户端，无需新增供应商分支；会员额度不能等同于按 token 美元费用，不为其虚构价格或登记为免费。配置参考：https://www.kimi.com/code/docs/kimi-code/models.html 。
- 统一由 `workflows/model_client.py`（`workflows.model_client`）提供 LLM 调用（httpx 直连 OpenAI 兼容接口，不依赖 openai SDK）。`pipeline/model_client.py` 仅为向后兼容的 re-export 层，新代码一律从 `workflows.model_client` 导入。
- 文本调用使用 `chat(prompt, system=...)`，返回 `(text, usage)`；`tests/eval_test.py` 存放模型内容分析评估，真实 LLM 测试标记 `slow`。默认 `python -m pytest tests/eval_test.py -v` 仅验证本地结构并跳过真实调用；`python -m pytest tests/eval_test.py -m slow` 显式运行全部 LLM 评估。
- `chat(prompt, system=..., temperature=1.0)` 文本入口默认温度为 1.0，兼容当前 Kimi Code K3 模型只接受 1 的限制；调用其他支持调温的模型时可显式传入 `temperature`，客户端原样传递。K3 的模型 ID 按官方小写填写（如 `k3-256k`）。其他已有调用入口的参数保持各自约定。
- 多 Agent 路由模块 `patterns/router.py` 提供 `route(query)` 统一入口：两层意图分类（关键词快速匹配 → LLM 兜底），分发给 github_search（GitHub Search API，`urllib.parse.quote` 编码查询参数）/ knowledge_query（扫描 `knowledge/articles/*.json` 关键词检索）/ general_chat（直接 LLM 回答）三个处理器。
- 配置存于项目根目录 `.env`（模板见 `.env.example`），受 `.gitignore` 保护，禁止提交真实 Key。
- 优先级：进程环境变量 > `.env`。LLM 统一使用 `LLM_PROVIDER`（默认 deepseek，仅作供应商标识）、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`；常用供应商的 base URL 和模型有内置默认值，未知的 OpenAI 兼容供应商需显式设置后两者。另有 `LOG_LEVEL`（DEBUG/INFO/WARNING/ERROR，默认 INFO）。流水线支持 `--provider` 参数指定供应商标识（`pipeline.py` 传入 `create_provider(name=...)`）。
- 新增模型价格只登记到 `MODEL_PRICES_USD`（USD / 1M tokens）；成本统一按模型单价计算 USD，不做汇率换算。调用方通过 `accumulate_usage` 把每次调用 `Usage` 累加进成本汇总 dict（如 `state["cost_tracker"]`），键为 `provider/model`，输出 USD 报告。

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

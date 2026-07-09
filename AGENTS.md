# AI 知识库助手 AGENTS.md

## 项目概述

本项目是一个自动化 AI 知识库助手，负责从 GitHub Trending 和 Hacker News 等渠道实时采集 AI/LLM/Agent 领域的技术动态，通过 AI 分析后结构化存储为 JSON 格式，并支持向 Telegram、飞书等多渠道分发。

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 语言 | Python 3.12 |
| AI 框架 | OpenCode + 国产大模型 |
| 工作流引擎 | LangGraph |
| 任务调度 | OpenClaw |
| 数据存储 | JSON 文件 |
| 消息分发 | Telegram Bot API / 飞书 Webhook |

## 编码规范

### 代码风格

- 遵循 PEP 8 规范
- 变量/函数名使用 `snake_case`
- 类名使用 `PascalCase`
- 常量使用 `UPPER_SNAKE_CASE`

### Docstring 规范

采用 Google 风格 docstring：

```python
def fetch_trending(repos: int = 25) -> list[dict]:
    """Fetch trending repositories from GitHub.

    Args:
        repos: Number of repositories to fetch. Defaults to 25.

    Returns:
        List of repository metadata dictionaries.

    Raises:
        APIError: If GitHub API request fails.
    """
```

### 强制要求

- **禁止裸 `print()`**：日志输出必须使用 `logging` 模块
- 类型注解必须完整
- 异常必须显式捕获和处理

## 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/          # Agent 定义文件
│   └── skills/          # 技能配置
├── knowledge/
│   ├── raw/             # 原始采集数据
│   └── articles/        # 结构化知识条目
├── AGENTS.md            # 本文件
└── README.md
```

## 知识条目 JSON 格式

```json
{
  "id": "gh-trending-20260709-001",
  "title": "项目名称",
  "source_url": "https://github.com/user/repo",
  "source_type": "github_trending | hacker_news",
  "summary": "AI 生成的中文摘要（150-300字）",
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
    "author": "username"
  }
}
```

## Agent 角色概览

| 角色 | 职责 | 触发条件 | 输出 |
|------|------|----------|------|
| **采集 Agent** | 从 GitHub Trending、HN 抓取 AI 相关内容 | 定时触发（每 6 小时） | `knowledge/raw/*.json` |
| **分析 Agent** | AI 分析内容质量、生成摘要和标签 | 采集完成后自动触发 | 更新后的 JSON（含 summary、tags） |
| **整理 Agent** | 去重、格式化、分发到各渠道 | 分析完成后自动触发 | 发布到 Telegram/飞书 |

## 红线（绝对禁止）

1. **禁止提交敏感信息**：API Key、Token、密码等不得进入代码或 commit
2. **禁止修改 `.env` 文件**：配置变更需手动操作
3. **禁止删除 `knowledge/` 目录**：历史数据不可删除
4. **禁止裸 `print()`**：必须使用 `logging` 模块
5. **禁止跨 Agent 直接调用**：必须通过工作流引擎协调
6. **禁止硬编码 URL**：所有外部链接必须从配置读取
7. **禁止无限制重试**：外部请求必须设置超时和重试上限
8. **禁止直接操作生产环境**：测试必须在开发环境完成

# ROADMAP

> 项目真实进度源。只有实现并验证过的事项才能进入「已完成」。

## 当前阶段

V1：采集-分析流水线可用，MCP 本地检索服务已完成（已知问题待修）。

## 已完成

- [x] GitHub Trending + RSS 采集 → LLM 分析 → 结构化 JSON 存储的四步流水线（`pipeline/pipeline.py`）
- [x] LLM 统一接入层（`pipeline/model_client.py`，httpx 直连 OpenAI 兼容接口）
- [x] CostTracker 成本追踪（`model_client.py`，按提供商 RMB 价格表估算 token 成本，`chat()` 成功后自动记录，Pipeline 结束输出 `tracker.report()`；已验证 deepseek 真实调用成本 0.0020 元 / 2 次）
- [x] 内容质量评分 hook（`hooks/check_quality.py`）+ JSON 校验 hook（`hooks/validate_json.py`）
- [x] Agent / skill 定义（`.opencode/agents/`、`.opencode/skills/`）
- [x] AGENTS.md 项目记忆
- [x] MCP 检索服务 `mcp_knowledge_server.py`：JSON-RPC 2.0 over stdio，支持 initialize / tools/list / tools/call / ping，3 个工具（search_articles / get_article / knowledge_stats），过滤 `test-` 前缀测试文件（已用管道模拟 stdio 验证）
- [x] 日志级别可配置：默认 INFO（`--verbose` 强制 DEBUG），可通过 `.env` 的 `LOG_LEVEL` 调整（已验证 DEBUG/WARNING/INFO 生效）

## 进行中

- （无）

## 待办

- [ ] **MCP `tools/call` 缺少初始化检查**：目前只有 `tools/list` 校验 `_session_initialized`，`tools/call` 在未握手时仍可执行，与 MCP 规范（initialize 后才能调工具）不一致。待修后对齐行为并验证。

## 阻塞

- （无）

## 最近验证

- 2026-08-05：MCP server 单管道模拟 stdio，initialize → tools/list → tools/call 均返回正确结果；`test-*.json` 已排除在统计外（30 篇：github 10 / rss 20）。

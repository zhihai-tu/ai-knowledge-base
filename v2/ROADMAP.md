# ROADMAP

> 项目真实进度源。只有实现并验证过的事项才能进入「已完成」。

## 当前阶段

V1：采集-分析流水线可用，MCP 本地检索服务已完成（已知问题待修）。

## 已完成

- [x] GitHub Trending + RSS 采集 → LLM 分析 → 结构化 JSON 存储的四步流水线（`pipeline/pipeline.py`）
- [x] LLM 统一接入层（`pipeline/model_client.py`，httpx 直连 OpenAI 兼容接口）
- [x] CostTracker 成本追踪（`model_client.py`，按模型单价 USD 计算，以 `(provider, model)` 为粒度记录，`chat()` 成功后自动记录，Pipeline 结束输出 `tracker.report()` 的 USD 报告；已验证 deepseek 真实调用成本 0.0020 元 / 2 次）
- [x] 内容质量评分 hook（`hooks/check_quality.py`）+ JSON 校验 hook（`hooks/validate_json.py`）
- [x] Agent / skill 定义（`.opencode/agents/`、`.opencode/skills/`）
- [x] AGENTS.md 项目记忆
- [x] MCP 检索服务 `mcp_knowledge_server.py`：JSON-RPC 2.0 over stdio，支持 initialize / tools/list / tools/call / ping，3 个工具（search_articles / get_article / knowledge_stats），过滤 `test-` 前缀测试文件（已用管道模拟 stdio 验证）
- [x] 日志级别可配置：默认 INFO（`--verbose` 强制 DEBUG），可通过 `.env` 的 `LOG_LEVEL` 调整（已验证 DEBUG/WARNING/INFO 生效）
- [x] 流水线 `--provider` 参数生效（`pipeline.py` 传入 `create_provider(name=...)`；已验证 `--provider qwen` 调用 qwen3.7-plus）
- [x] 百炼专属网关接入：`model_client.py` 的 qwen 提供商支持 `QWEN_BASE_URL` / `QWEN_MODEL` 环境变量覆盖默认 base_url/模型，`.env` 已配置专属网关地址与 key（已验证 200 OK，真实调用回复正常）
- [x] 成本计费单一价格表重构：删除 `PROVIDER_PRICES_CNY` 与汇率折算，统一按 `MODEL_PRICES_USD` 计算并输出 USD 报告，`CostTracker` 按 `(provider, model)` 记录（已验证多提供商/多模型混合报告按各自单价准确分列与汇总）

## 进行中

- （无）

## 待办

- [ ] **MCP `tools/call` 缺少初始化检查**：目前只有 `tools/list` 校验 `_session_initialized`，`tools/call` 在未握手时仍可执行，与 MCP 规范（initialize 后才能调工具）不一致。待修后对齐行为并验证。

## 阻塞

- （无）

## 最近验证

- 2026-08-09：百炼专属网关真实调用验证通过（`LLM_PROVIDER=qwen`，14 in / 49 out tokens，200 OK）。
- 2026-08-05：MCP server 单管道模拟 stdio，initialize → tools/list → tools/call 均返回正确结果；`test-*.json` 已排除在统计外（30 篇：github 10 / rss 20）。

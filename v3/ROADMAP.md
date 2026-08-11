# ROADMAP

> 项目真实进度源。只有实现并验证过的事项才能进入「已完成」。

## 当前阶段

V3（初始化）：基于 V2 拷贝代码骨架，将在 V2 基础上引入多 Agent 能力（agent 架构待设计）。

## 已完成

- 2026-08-11：多 Agent 路由首个模块落地 `patterns/router.py`（两层意图分类 + 三处理器）；LLM 调用统一入口迁移至 `workflows/model_client.py`，`pipeline/model_client.py` 改为向后兼容 re-export 层。已验证：关键词路由、GitHub 中文搜索（quote 编码）、LLM 分类兜底、general_chat、兼容层导入。
- 2026-08-11：knowledge_query 改为从 `knowledge/articles/index.json` 检索（`_load_articles()`），新增 `rebuild_index()` 与 `--rebuild-index` 入口；index 已从 131 篇真实文章生成。已验证：`搜一下 agent` / `查一下 rag` 均可命中并按 score 排序。
- 2026-08-11：knowledge_query 关键词无命中时回退到 LLM 直读知识库全文回答（`_llm_knowledge_answer()`），不做分词；句子式查询（如「搜索最近的 AI Agent 框架」）可正常得到基于知识库内容的回答。已验证：关键词路径零成本直配、句子式查询走 LLM 兜底。
- 2026-08-11：路由调用轨迹记录 `logs/router_trace.jsonl`（每次 `route()` 追加：query / keyword_hit / hit_keyword / llm_intent / llm_error / final_intent / outcome / llm_cost / llm_calls），并提供 `--trace-stats` 聚合统计（关键词命中率、LLM 兜底率、命中但空结果数、命中关键词分布）。已验证：三条样例查询正确落盘，统计能暴露「首字'搜'」将句子式查询误路由进 knowledge_query 的问题。
- 2026-08-11：CLI 输出规范化：`route_with_meta()` 返回结构化 `RouteResult`（意图/关键词命中/LLM 成本），`route()` 保持纯文本兼容；CLI 输出含 [输入]/[路由]/[关键词]/[LLM]/[回答] 分块，调用 LLM 时展示调用次数与估算成本（复用 model_client 的 `chat_with_retry`+`response_cost` 用量追踪）。已验证：关键词命中路径无 LLM 行、句子式/通用对话正确展示 LLM 次数与成本、`route()` 纯文本兼容。
- 2026-08-11：INFO 及以上日志（route 意图、httpx 请求、LLM 用量）改写入 `logs/router.log`，控制台只输出规范化结果，不再打印日志。已验证：控制台干净、router.log 记录完整。
- 2026-08-11：意图识别修正：移除关键词层「首字'搜/查/找/看'」的启发式硬路由（会把「搜索最近的 AI Agent 框架」误判为 knowledge_query），歧义查询一律交 LLM 分类；`_llm_route` 分类为 github_search 时在同一调用内输出英文搜索词（格式 `github_search|关键词`），github handler 优先使用。已验证：「搜索最近的 AI Agent 框架」→ github_search 并搜到 superpowers/langchain/MetaGPT；「查一下 rag」仍判 knowledge_query；「github 搜索 X」关键词直配不受影响。
- 2026-08-11：GitHub 搜索网络容错：新增 `_fetch_github()`，经代理连接失败（TLS/超时）自动回退直连并重试 2 次，CLI 输出 `[GitHub] 已改用直连（原代理连接失败）`。排查中发现关键坑：复用同一 `urllib Request` 对象时 ProxyHandler 缓存 `proxy_host` 导致直连仍走代理，每次尝试必须新建 Request。已验证：代理坏时 3/3 直连成功搜到结果。
- 2026-08-11：GitHub 搜索结果精简：新增 `_truncate()`，仓库描述截断为 100 字符（超长描述如几万字不再刷屏）；代理回退提示语改为明确的「已改用直连（原代理连接失败）」。已验证：超长描述仓库正常截断，死代理下 `via_direct=True` 且直连返回结果。

## 进行中

- （无）

## 待办

- [ ] 设计多 Agent 架构整体方案：agent 分工、编排方式、与 Router 模块的衔接
- [ ] V3 基线验证：拷贝自 V2 的流水线 / MCP server 在 V3 环境可运行
- [ ] [可选] 路由探针模式：关键词命中时也调用一次 LLM 记录其意图，作为「命中得对不对」的对照数据（调试期按需开启，会增加 LLM 调用成本）

## 阻塞

- （无）

## 最近验证

- 2026-08-11：V3 目录初始化，代码骨架自 V2 拷贝完成（pipeline / hooks / mcp_knowledge_server.py / 配置文件）。

# ROADMAP

> 项目真实进度源。只有实现并验证过的事项才能进入「已完成」。

## 当前阶段

V3（初始化）：基于 V2 拷贝代码骨架，将在 V2 基础上引入多 Agent 能力（agent 架构待设计）。

## 已完成

- 2026-09-08：统一 `.env` 与 `.env.example` 的 LLM 变量注释，使用供应商无关的字段说明，并在 AGENTS.md 约定切换供应商只修改配置值。已验证：修改前后两份配置文件非注释内容摘要一致，配置值及密钥未变。
- 2026-09-08：Kimi Code 配置准备完成：`.env` 与 `.env.example` 切换为 `kimi-code` / `https://api.kimi.com/coding/v1` / `kimi-for-coding`，保留用户的密钥行；AGENTS.md 记录配置与会员计费边界，复用原 OpenAI 兼容客户端。已验证：现有 Anaconda Python + httpx 下加载配置、目标请求地址、模型字段及 chat_json 解析（离线 MockTransport），`.env` 仍被 Git 忽略。待用户维护 Kimi Code 密钥后验证真实调用；当前未登记套餐 token 单价，成本警告及 0 值不代表免费或实际账单。官方参考：https://www.kimi.com/code/docs/kimi-code/models.html 。
- 2026-09-02：新增 `tests/cost_guard.py` 多 Agent 人民币预算守卫：`CostRecord` 记录单次调用；`CostGuard` 累计输入/输出 token 与成本，提供 80% 预警、超预算异常、按节点成本报告及 JSON 保存；模块自检覆盖成本累计、预警阈值与超限异常。已验证：`python3 tests/cost_guard.py` 通过。
- 2026-09-02：补充 `glm-5.3-flash` 成本价格：按 Z.AI 官方价格页当前 5 折促销价登记为输入 `$0.075`、输出 `$0.25` / 1M tokens，并注明 2026-09-09 24:00（UTC+8）促销截止时间及原价；已通过 `calculate_cost()` 回归验证。
- 2026-09-02：统一 LLM 供应商配置：`workflows/model_client.py` 改为只读取 `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`，删除供应商专属 API Key/base URL/model 环境变量；`PROVIDER_DEFAULTS` 仅保留常用供应商默认值，未知 OpenAI 兼容供应商可直接通过通用配置接入；同步更新 `pipeline/model_client.py` re-export、`.env.example` 和本文件说明。已验证：两个模块 `py_compile` 通过，隔离配置测试覆盖通用配置、已知供应商默认值、未知供应商、缺少通用配置和兼容导出；使用 uv 隔离环境对智谱 `glm-5.3-flash` 完成真实 `chat_with_retry()` 与 `chat_json()` 调用，返回正常。
- 2026-09-02：清理 `nodes.py` 死代码（2 个无效节点 + 4 个孤儿）：删除旧版四维度 `review_node`（graph 实际用 reviewer.py 五维度版，零引用）、临时测试节点 `review_node_test`（graph.py 仅存一行注释引用，一并删除）、及仅被死代码引用的 `_review_articles` / `REVIEW_SYSTEM`（与 reviewer.py 的五维度版并存）/ `PASS_REVIEW_SCORE` / `FORCE_PASS_ITERATION`；模块 docstring 修正为「4 个节点函数」并注明 review 独立在 reviewer.py。已验证：`py_compile` 通过、6 个符号已不存在、4 个有效节点齐全、`build_graph()` 编译、路由断言、collect/organize 的 plan 消费回归通过。
- 2026-09-02：Planner 策略规划落地（流水线前置规划节点，多 Agent 化第一步）。① `state.py` KBState 新增 `plan` 字段（结构化策略报告）；② 新增 `workflows/planner.py`：`plan_strategy(target_count)` 返回三档策略 lite/standard/full（per_source_limit 5/10/20、relevance_threshold 0.7/0.5/0.4、max_iterations 1/2/3，各含 rationale 选档理由），target_count 缺省读环境变量 `PLANNER_TARGET_COUNT`（默认 10，空串回落默认）；`planner_node` 返回 `{"plan": plan}`；③ `graph.py` 接入 `planner_node` 为入口节点（plan → collect → analyze → organize → review），`route_after_review` 改读 `plan.max_iterations`（无 plan 默认 3），废弃并删除 `state.MAX_ITERATIONS` 常量；④ 三节点消费 plan：collect_node 读 `per_source_limit`（默认 `COLLECT_LIMIT`=10）传入 GitHub Search `per_page`；organize_node 读 `relevance_threshold`（默认 0.5，×10 映射为 1-10 分制过滤线，删除 `MIN_ACCEPT_SCORE=6`；无 plan 行为与 standard 档一致——经查现有库 10 条均为 8-9 分，6 分历史线从未实际起过滤作用，故维持 0.5 不改）；reviewer 不读 plan（见下条）。⑤ review 循环出口唯一化：评审过程中曾按需求在 review_node 内加「iteration ≥ plan.max_iterations 强制通过」兜底，该兜底会使 human_flag 异常终点不可达（节点先返回 passed=True → 路由走 save），已撤销——review_node 只负责评审与 iteration 递增，「达上限 → human_flag 人工介入」由 graph 路由独占。⑥ 全部相关 docstring 与实际行为对齐（state/graph/nodes/reviewer/planner 流水线描述加 plan 前缀、MAX_ITERATIONS 引用清理、合并 route_after_review 双 docstring、planner rationale 对齐真实路由语义：max_iterations 为总审核轮次，重做轮次 = 值-1，lite 档未通过即转人工）。已验证：三档边界/参数/rationale/环境变量默认与空串回落断言；collect limit 传递（mock `_fetch_github_search`）；organize 阈值映射三分支（0.5→5 分 / 0.7→7 分 / 0.4→4 分，mock）；reviewer 低分 → iteration 递增 → 路由 human_flag 全链路（mock chat_json）；route_after_review 三分支断言；`build_graph()` 编译通过。待办：含 planner 的真实 LLM 端到端。
- 2026-08-18：`workflows/model_client.py` 精简重构（693 行 → 约 500 行）：① 成本计算统一为 `accumulate_usage` 方案，移除 `CostTracker` 类与全局 `tracker` 单例（避免同一批调用被两套成本机制重复记账），成本改由调用方累计进 `state.cost_tracker`，graph/pipeline 成本报告改用 state 汇总（`pipeline.py` `analyze_item` 改为返回 `(item, usage)`）；② 移除 `LLMProvider` ABC 抽象（全项目仅一个 OpenAI 兼容实现，属过度设计），合并为单个具体 `LLMProvider` 类；③ 删除死代码 `estimate_tokens`（无业务调用）；④ 调用入口统一为 `chat_json`，删除 `quick_chat`；⑤ `response_cost` 并入 `calculate_cost`；⑥ qwen/glm 的 `BASE_URL`/`MODEL` 覆盖环境变量统一进 `PROVIDER_CONFIGS` 配置项，删除 create_provider 里的重复分支；同步更新 `pipeline/model_client.py` re-export 层、AGENTS.md。已验证：全部相关文件 `python3 -m py_compile` 通过、跨模块导入正常、re-export 层符号齐全；router.py / reviewer.py / nodes.py / graph.py 引用全部同步。
- 2026-08-18：glm 提供商接入：`model_client.py` 新增 `glm` 提供商（官方默认 `https://open.bigmodel.cn/api/paas/v4`，模型 `glm-5.2`，`GLM_API_KEY`），支持 `GLM_BASE_URL` / `GLM_MODEL` 环境变量覆盖（商汤 SenseNova `https://token.sensenova.cn/v1` 第三方接入）；`glm-5.2` 价格登记 MODEL_PRICES_USD（约 $1.40/$4.40，第三方参考值待核对官方价目）。已验证：配置加载、覆盖逻辑、SenseNova 真实调用（单条 200 OK；graph 全流程 analyze 6/10 成功、review 通过）。
- 2026-08-18：SenseNova 429 突发限流适配：`model_client.py` 对 429 退避时间 ×5（5s/10s，原 1s/2s），`nodes.py` analyze 相邻请求间隔 `ANALYZE_INTERVAL_SECONDS=2s` 平滑请求速率。根因确认：SenseNova 返回 `Throttling.BurstRate`（"scale requests more smoothly over time"），无 Retry-After 头，属短期突发限流，冷却约 1 分钟后单条请求恢复。已验证：修复后 429 退避生效，10 条分析中 6 条成功（glm-5.2 限流仍严，可调大间隔提升成功率）。
- 2026-08-18：analyze 阶段实时进度输出：逐条打印「分析 X/10: title ...」+ score/失败结果（flush=True），解决 glm-5.2 推理模型响应慢、串行调用时无中间输出导致的「看似卡死」困惑。已验证：假 LLM 用例下 3 条进度逐条打印、失败提示、汇总行正确。
- 2026-08-18：graph 运行体验优化四项：① analyze 每次调用 usage 累计进 `state.cost_tracker`（此前只累计 review，成本被低估）；② reviewer 审核全部 analyses（撤销 REVIEW_LIMIT=5 前 5 条限制，输出「审核 8/8 条」）；③ collect 逐条打印仓库明细（title + ⭐stars）；④ graph `__main__` 输出美化（review_feedback 分段悬挂缩进、cost_tracker 按模型分行）+ 末尾 `tracker.report()` 输出含全部节点的完整成本报告。已验证：假 LLM 用例 analyze 3 条 cost_tracker calls=3、reviewer 审核 8/8、`_show_review_feedback`/`_show_cost` 排版正确，`python3 -m py_compile` 通过。真实 qwen 调用端到端同样走通（10/10 分析、审核 8.30 分、保存 10 篇）。
- 2026-08-18：graph 阶段块标题语义明确化：`--- step X | node ---`（LangGraph stream 在节点完成后 yield，语义含糊）改为 `--- step X | node 完成 ---`，并加阶段间空行分隔。已验证：`py_compile` 通过，模拟输出阶段块带空行与「完成」字样。
- 2026-08-11：多 Agent 路由首个模块落地 `patterns/router.py`（两层意图分类 + 三处理器）；LLM 调用统一入口迁移至 `workflows/model_client.py`，`pipeline/model_client.py` 改为向后兼容 re-export 层。已验证：关键词路由、GitHub 中文搜索（quote 编码）、LLM 分类兜底、general_chat、兼容层导入。
- 2026-08-11：knowledge_query 改为从 `knowledge/articles/index.json` 检索（`_load_articles()`），新增 `rebuild_index()` 与 `--rebuild-index` 入口；index 已从 131 篇真实文章生成。已验证：`搜一下 agent` / `查一下 rag` 均可命中并按 score 排序。
- 2026-08-11：knowledge_query 关键词无命中时回退到 LLM 直读知识库全文回答（`_llm_knowledge_answer()`），不做分词；句子式查询（如「搜索最近的 AI Agent 框架」）可正常得到基于知识库内容的回答。已验证：关键词路径零成本直配、句子式查询走 LLM 兜底。
- 2026-08-11：路由调用轨迹记录 `logs/router_trace.jsonl`（每次 `route()` 追加：query / keyword_hit / hit_keyword / llm_intent / llm_error / final_intent / outcome / llm_cost / llm_calls），并提供 `--trace-stats` 聚合统计（关键词命中率、LLM 兜底率、命中但空结果数、命中关键词分布）。已验证：三条样例查询正确落盘，统计能暴露「首字'搜'」将句子式查询误路由进 knowledge_query 的问题。
- 2026-08-11：CLI 输出规范化：`route_with_meta()` 返回结构化 `RouteResult`（意图/关键词命中/LLM 成本），`route()` 保持纯文本兼容；CLI 输出含 [输入]/[路由]/[关键词]/[LLM]/[回答] 分块，调用 LLM 时展示调用次数与估算成本（复用 model_client 的 `chat_with_retry`+`response_cost` 用量追踪）。已验证：关键词命中路径无 LLM 行、句子式/通用对话正确展示 LLM 次数与成本、`route()` 纯文本兼容。
- 2026-08-11：INFO 及以上日志（route 意图、httpx 请求、LLM 用量）改写入 `logs/router.log`，控制台只输出规范化结果，不再打印日志。已验证：控制台干净、router.log 记录完整。
- 2026-08-11：意图识别修正：移除关键词层「首字'搜/查/找/看'」的启发式硬路由（会把「搜索最近的 AI Agent 框架」误判为 knowledge_query），歧义查询一律交 LLM 分类；`_llm_route` 分类为 github_search 时在同一调用内输出英文搜索词（格式 `github_search|关键词`），github handler 优先使用。已验证：「搜索最近的 AI Agent 框架」→ github_search 并搜到 superpowers/langchain/MetaGPT；「查一下 rag」仍判 knowledge_query；「github 搜索 X」关键词直配不受影响。
- 2026-08-11：GitHub 搜索网络容错：新增 `_fetch_github()`，经代理连接失败（TLS/超时）自动回退直连并重试 2 次，CLI 输出 `[GitHub] 已改用直连（原代理连接失败）`。排查中发现关键坑：复用同一 `urllib Request` 对象时 ProxyHandler 缓存 `proxy_host` 导致直连仍走代理，每次尝试必须新建 Request。已验证：代理坏时 3/3 直连成功搜到结果。
- 2026-08-11：GitHub 搜索结果精简：新增 `_truncate()`，仓库描述截断为 100 字符（超长描述如几万字不再刷屏）；代理回退提示语改为明确的「已改用直连（原代理连接失败）」。已验证：超长描述仓库正常截断，死代理下 `via_direct=True` 且直连返回结果。
- 2026-08-11：Supervisor 监督模式落地 `patterns/supervisor.py`：Worker 产出 JSON 分析报告 → Supervisor 按准确性/深度/格式三维度评分（score=round(均值)）输出 `{"passed","score","feedback"}`；score≥7 通过，否则带反馈重做（最多 `max_retries` 轮），耗尽后强制返回并附 warning。已验证：真实 DeepSeek 调用首轮通过；monkeypatch 用例覆盖「耗尽报 warning」「第2轮通过」「Worker LLM 失败降级」三条分支。返回值新增 `rounds`（每轮 attempt/score/passed/feedback），CLI 改为分轮次展示得分与最终结果（含输出预览、警告行），日志降为 WARNING 保持控制台干净。已验证：真实调用渲染正确、monkeypatch rounds 字段齐全。
- 2026-08-11：`workflows/nodes.py` organize 新增跨批次 URL 去重：新增 `_load_existing_urls()` 扫描 `knowledge/articles/*.json`（排除 index.json / test-*）收集历史 `source_url`，`_build_articles` 将其并入 `seen_urls`，与当前批次内去重共用同一逻辑，避免热门仓库重复入库（此前 157 篇仅 52 个唯一 URL）。已验证：`_load_existing_urls()` 返回 49 与全文件直接扫描一致；真实管线运行 0 条（GitHub top10 全部命中历史，符合预期）。

## 进行中

- `workflows/reviser.py` 修订节点：`revise_node`（读取 `state["analyses"]` 与 `state["review_feedback"]`，反馈注入修订 prompt，LLM 返回改写后的 analyses，temperature=0.4 允许创造性改写；analyses 或 feedback 为空时返回 `{}` 跳过；按 source_id 合并改写结果、保持原顺序，调用失败/输出非法时保留原 analyses 不阻塞流程；成本累计进 `state.cost_tracker`）。已验证：`py_compile` 通过，monkeypatch 覆盖 6 分支（空 analyses/空 feedback/正常改写+temperature 与成本断言/调用失败/输出非数组/缺 id 条目沿用）；已接入 `graph.py` 编排（revise → review 重做循环边，含 planner 的 `build_graph()` 编译通过）。待办：含 planner 的真实 LLM 端到端验证。
- LangGraph 工作流节点落地 `workflows/nodes.py`：5 个纯函数节点（collect→analyze→organize→review→save）已实现，评分沿用 1-10（与现有库一致，过滤线现由 `plan.relevance_threshold` 控制、审核通过线 7 分），节点逻辑经 monkeypatch（假 GitHub API + 假 LLM）验证通过。待办：真实 LLM 端到端验证。
- 审核节点独立模块 `workflows/reviewer.py`：新增 `review_node`（审核对象改为 `state["analyses"]`，5 维度加权评分 摘要25%/深度25%/相关20%/原创15%/格式15%，加权总分由代码重算、≥7.0 通过，审核全部 analyses，temperature=0.1，LLM 调用失败自动通过）；`graph.py` 已切换到该节点（`workflows/nodes.py` 旧 review_node 已于 2026-09-02 删除）；`model_client.py` 新增 `chat_json`（返回 (parsed_json, usage)）与 `accumulate_usage`（并入 state 成本汇总 dict）。已验证：monkeypatch 全分支（PASS/FAIL/LLM失败/缺scores/空analyses/分数钳制/成本累计），`build_graph()` 编译通过，真实 qwen 调用端到端审核通过。
- LangGraph 编排 `workflows/graph.py`：StateGraph(KBState) 组装 plan→collect→analyze→organize→review 流水线，review 后按 `route_after_review` 三路分支（通过→save；未通过且未达 `plan.max_iterations`→revise 形成重做循环；达上限→human_flag 异常终点），`build_graph()` 返回编译后 app，`__main__` 流式打印每节点关键输出。已验证：`build_graph()` 编译、路由三分支断言、stub 节点动态跑通 FAIL 路径（review×3 → revise×2 → human_flag → END）与 PASS 路径（→ save）。

## 待办

- [ ] 含 planner 的真实 LLM 端到端验证：plan → collect → analyze → organize → review 全流水线带真实 GitHub API + LLM 跑通（lite/standard 各一档，确认 plan 参数实际生效）
- [ ] 设计多 Agent 架构整体方案：agent 分工、编排方式、与 Router 模块的衔接
- [ ] V3 基线验证：拷贝自 V2 的流水线 / MCP server 在 V3 环境可运行
- [ ] [可选] 路由探针模式：关键词命中时也调用一次 LLM 记录其意图，作为「命中得对不对」的对照数据（调试期按需开启，会增加 LLM 调用成本）
- [ ] 已收录仓库的刷新更新机制：跨批次去重会拦截「已收录过、想重新采集生成新版本」的仓库（如 AutoGPT 迭代升级后想重收），需设计刷新/强制覆盖开关（如按 source_url 覆盖、CLI 传参跳过历史去重），当前流程无此需求暂不实现
- [ ] 0 条结果短路：跨批次去重将全部条目过滤后管线仍空跑 review/save 并重复消耗 GitHub API + LLM 分析成本，考虑 organize 产出 0 条时提前结束

## 阻塞

- （无）

## 最近验证

- 2026-09-02：planner/plan 全链路 mock 验证：三档策略边界与参数、环境变量默认与空串回落、collect limit 传递、organize 阈值映射三分支、reviewer 低分 → iteration 递增 → human_flag 出口、route_after_review 三分支、`build_graph()` 编译。
- 2026-08-11：V3 目录初始化，代码骨架自 V2 拷贝完成（pipeline / hooks / mcp_knowledge_server.py / 配置文件）。

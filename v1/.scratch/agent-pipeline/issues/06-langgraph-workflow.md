# 06 — LangGraph 工作流编排

**What to build:** 使用 LangGraph 编排 collector → analyzer → organizer 的串行流水线，实现 Agent 之间的数据传递和状态管理。

**Blocked by:** 01 — 基础设施搭建, 02 — GitHub Trending 采集器, 03 — 数据验证工具, 04 — Analyzer Agent 实现, 05 — Organizer Agent 实现

**Status:** ready-for-agent

- [ ] 创建 `workflow/pipeline.py`，定义 LangGraph StateGraph
- [ ] 实现三个节点：collector_node、analyzer_node、organizer_node
- [ ] 定义状态传递格式（文件路径或数据对象）
- [ ] 实现串行边连接：collector → analyzer → organizer
- [ ] 添加错误处理节点（捕获上游失败）
- [ ] 实现 `run_pipeline()` 函数，启动完整流水线
- [ ] 添加单元测试，mock 各节点逻辑
- [ ] 验证：运行 `run_pipeline()` 后，knowledge/ 目录生成完整数据
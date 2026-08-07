# 13 — 端到端集成测试

**What to build:** 实现完整的端到端测试，验证从采集到分发的整个流水线。

**Blocked by:** 07 — Hacker News 采集器, 08 — 定时调度器, 09 — 错误处理与重试策略, 10 — Telegram 分发, 11 — 飞书分发, 12 — 进度追踪

**Status:** ready-for-agent

- [ ] 创建 `tests/integration/` 目录
- [ ] 实现 `test_full_pipeline.py`，mock 所有外部 API
- [ ] 测试完整流程：采集 → 分析 → 整理 → 分发
- [ ] 测试错误场景：网络失败、API 限流、数据格式错误
- [ ] 测试断点续跑：从失败节点恢复执行
- [ ] 添加性能测试：验证大规模数据处理能力
- [ ] 验证：`pytest tests/integration/` 全部通过
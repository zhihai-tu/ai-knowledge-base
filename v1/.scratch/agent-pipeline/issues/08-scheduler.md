# 08 — 定时调度器

**What to build:** 实现定时触发机制，支持每天 UTC 0:00 自动运行流水线，可配置调度时间。

**Blocked by:** 06 — LangGraph 工作流编排

**Status:** ready-for-agent

- [ ] 实现 `scheduler/cron.py`，使用 schedule 库或 cron 表达式
- [ ] 支持配置调度时间（默认每天 UTC 0:00）
- [ ] 实现守护进程模式，后台持续运行
- [ ] 添加日志记录调度触发时间
- [ ] 支持手动触发（`python -m scheduler.run`）
- [ ] 添加单元测试，验证调度逻辑
- [ ] 验证：启动调度器后，到指定时间自动触发流水线
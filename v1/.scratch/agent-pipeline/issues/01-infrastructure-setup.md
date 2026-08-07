# 01 — 基础设施搭建

**What to build:** 项目的工程基础设施，包括依赖管理、日志配置、测试框架，为后续所有 Agent 开发提供基础支撑。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] 创建 `pyproject.toml`，配置项目元数据和依赖（httpx、langgraph、schedule 等）
- [ ] 配置 logging 模块，支持结构化日志输出到文件和控制台
- [ ] 配置 pytest 测试框架，创建 `tests/` 目录结构
- [ ] 添加 `.env.example` 文件，列出所需的环境变量模板
- [ ] 验证：`pip install -e .` 成功，`pytest` 可运行
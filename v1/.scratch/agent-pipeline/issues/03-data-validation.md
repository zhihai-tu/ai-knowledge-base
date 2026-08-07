# 03 — 数据验证工具

**What to build:** 实现 JSON Schema 验证工具，确保采集、分析、整理各阶段的数据格式符合 AGENTS.md 中定义的规范。

**Blocked by:** 01 — 基础设施搭建

**Status:** ready-for-agent

- [ ] 定义 JSON Schema 文件：`specs/schemas/raw.json`、`specs/schemas/analyzed.json`、`specs/schemas/published.json`
- [ ] 实现 `utils/validator.py`，使用 jsonschema 库验证数据格式
- [ ] 支持验证单个条目和批量验证
- [ ] 验证失败时返回详细的错误信息
- [ ] 添加单元测试，覆盖各种验证场景
- [ ] 验证：对现有 `knowledge/raw/` 和 `knowledge/articles/` 数据验证通过
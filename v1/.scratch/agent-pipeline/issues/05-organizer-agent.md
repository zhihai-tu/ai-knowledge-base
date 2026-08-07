# 05 — Organizer Agent 实现

**What to build:** 实现 organizer Agent 的核心逻辑，读取已分析的数据，进行去重、格式化，生成标准化的知识条目 JSON。

**Blocked by:** 01 — 基础设施搭建

**Status:** ready-for-agent

- [ ] 实现 `agents/organizer.py`，读取 analyzed 数据
- [ ] 实现去重逻辑（基于 source_url）
- [ ] 格式化数据，生成符合 schema 的标准条目
- [ ] 更新 `status` 字段为 `"published"`
- [ ] 保存到 `knowledge/articles/` 目录（覆盖或新建）
- [ ] 添加单元测试，验证去重和格式化逻辑
- [ ] 验证：对 analyzed 数据运行整理后，articles 目录生成最终条目
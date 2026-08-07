# 04 — Analyzer Agent 实现

**What to build:** 实现 analyzer Agent 的核心逻辑，读取 `knowledge/raw/` 数据，为每条内容打 3 维度标签（category、tags、quality_score）。

**Blocked by:** 01 — 基础设施搭建

**Status:** ready-for-agent

- [ ] 实现 `agents/analyzer.py`，读取 raw 数据并进行分析
- [ ] 实现 3 维度标签打分逻辑（category、tags、quality_score）
- [ ] 支持批量处理多个 JSON 文件
- [ ] 更新 `status` 字段为 `"analyzed"`
- [ ] 保存分析结果到 `knowledge/articles/` 目录
- [ ] 添加单元测试，验证标签打分逻辑
- [ ] 验证：对现有 raw 数据运行分析后，articles 目录生成新文件
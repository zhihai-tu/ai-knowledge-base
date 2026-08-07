# 11 — 飞书分发

**What to build:** 实现飞书 Webhook 集成，将整理后的知识条目发送到飞书群组。

**Blocked by:** 05 — Organizer Agent 实现

**Status:** ready-for-agent

- [ ] 实现 `distributors/feishu.py`，使用 httpx 调用飞书 Webhook
- [ ] 支持配置 Webhook URL（从环境变量读取）
- [ ] 实现消息格式化（富文本卡片）
- [ ] 支持批量发送（避免触发速率限制）
- [ ] 更新 `distribution.feishu` 字段为 `true`
- [ ] 添加单元测试，mock 飞书 API
- [ ] 验证：配置 Webhook 后，运行分发能成功发送消息
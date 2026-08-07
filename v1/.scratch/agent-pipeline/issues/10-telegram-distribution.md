# 10 — Telegram 分发

**What to build:** 实现 Telegram Bot API 集成，将整理后的知识条目发送到指定频道或群组。

**Blocked by:** 05 — Organizer Agent 实现

**Status:** ready-for-agent

- [ ] 实现 `distributors/telegram.py`，使用 httpx 调用 Telegram Bot API
- [ ] 支持配置 Bot Token 和 Chat ID（从环境变量读取）
- [ ] 实现消息格式化（标题、摘要、链接、标签）
- [ ] 支持批量发送（避免触发速率限制）
- [ ] 更新 `distribution.telegram` 字段为 `true`
- [ ] 添加单元测试，mock Telegram API
- [ ] 验证：配置 Token 后，运行分发能成功发送消息
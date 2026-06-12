# Changelog

## [1.0.0] - 2026-06-05

### Added
- 初始版本：Skill 版本监控器
- 监控所有 openclaw-workspaces 下 Skill 的 Git 变更
- 自动版本递增判断（patch/minor/major）
- 自动 CHANGELOG 写入
- 飞书通知推送

### Notes
- 使用方式：定时 HEARTBEAT 触发或手动调用 execute()
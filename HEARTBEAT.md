# HEARTBEAT.md — 定时任务

## 1. 自学习通知队列检查

检查 `events/notifications/` 目录下的 pending 通知，通过 `message` tool 发送。

```bash
python3 -c "
import json, os
queue_dir = os.path.expanduser('~/openclaw-workspaces/ai-order/events/notifications')
if not os.path.isdir(queue_dir):
    exit()
for f in sorted(os.listdir(queue_dir)):
    if not f.endswith('.json'): continue
    path = os.path.join(queue_dir, f)
    with open(path) as fh:
        data = json.load(fh)
    if data.get('status') == 'pending':
        print(f'PENDING: {f} | {data.get(\"title\",\"\")} | priority={data.get(\"priority\",\"normal\")}')
"
```

如果有 PENDING 通知：
1. 读取每个 pending 的 JSON 文件
2. 根据 `channels` 字段，用 `message` tool 发送到对应通道：
   - `auto`: **不指定 channel 和 target**，让 message tool 自动路由到当前会话通道（飞书/钉钉均可）
   - `feishu`: action=send, channel=feishu
   - `dingtalk`: action=send, channel=dingtalk
3. 每个通道都发送成功后，将文件中的 `status` 改为 `sent`，加 `sent_at` 时间戳

**关键**：`auto` 模式下，`message(action=send, message=...)` 不带 channel/target 参数，这样 Agent 绑定在飞书就走飞书，移植到钉钉就走钉钉。

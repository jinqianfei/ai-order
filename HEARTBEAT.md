# HEARTBEAT.md — 定时任务

## 1. 自学习通知队列检查

检查 `events/notifications/` 目录下的 pending 通知，通过 `message` tool 发送到飞书。

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
2. 用 `message` tool（action=send, channel=feishu）发送 `message` 字段内容
3. 发送成功后将文件中的 `status` 改为 `sent`，加 `sent_at` 时间戳

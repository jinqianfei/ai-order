# skill-openclaw-deploy

将 OpenClaw AI 建单助手部署到 AWS EC2 的完整方案。支持 WebChat + 飞书 Channel 接入，国内无需翻墙访问。

## 功能

- 一键部署 OpenClaw 到 AWS EC2（新加坡）
- 配置 Cloudflare Tunnel 解决国内访问
- 配置飞书 Webhook Channel
- 设备 Token 免批准登录
- Skill 自动同步

## 架构

```
用户浏览器 ──→ Cloudflare Tunnel ──→ EC2 Gateway (localhost:18789)
                (国内直连)              ↓
                                   ai-order agent
                                       ↓
                                   AWS RDS (neo)
```

## 踩坑清单（8个）

1. **Token 登录** - 选 Token 方式，避免每次批准
2. **RDS 访问权限** - EC2 安全组添加到 RDS
3. **Cloudflare URL 变化** - 重启后 URL 变化，需固定域名
4. **Skill 版本同步** - 排除 .git 和 sessions/ 目录
5. **Gateway 绑定** - bind=loopback + Tunnel 暴露
6. **Node PATH** - systemd service 设置正确的 NVM PATH
7. **数据库配置** - 云端用 neo 不是 neondb
8. **Token 生成** - 直接写 paired.json 生成可用 token

## 文件结构

```
skill_openclaw_deploy/
├── SKILL.md
├── __init__.py
├── config/
│   └── deploy_config.yaml.example
├── scripts/
│   └── deploy.sh
└── docs/
    └── DEPLOY_GUIDE.md
```
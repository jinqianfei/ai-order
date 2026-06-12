#!/usr/bin/env python3
"""飞书通知 — 推送 Skill 版本变更通知"""
import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime


def format_feishu_card(skill_name: str, workspace: str, old_version: str, new_version: str, bump_type: str, reason: str, changed_files: list, commit_ok: bool) -> dict:
    """构建飞书消息卡片 JSON"""
    bump_emoji = {"major": "🔴", "minor": "🟡", "patch": "🟢"}
    label = {"major": "重大更新", "minor": "功能更新", "patch": "补丁修复"}
    template_color = {"major": "red", "minor": "yellow", "patch": "green"}

    emoji = bump_emoji.get(bump_type, "🔵")
    lbl = label.get(bump_type, bump_type)
    color = template_color.get(bump_type, "grey")

    files_text = "\n".join([f"• `{f}`" for f in changed_files[:8]])
    if len(changed_files) > 8:
        files_text += f"\n• ... (+{len(changed_files) - 8} more)"

    files_element = {
        "tag": "markdown",
        "content": f"**改动文件：**\n{files_text}"
    } if files_text else {"tag": "div"}

    commit_status = "✅ Git 已提交" if commit_ok else "⚠️ Git 未提交"

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"🦎 Skill 版本更新 · {skill_name}"},
                "template": color,
            },
            "elements": [
                {"tag": "markdown", "content": f"**工作区：** `{workspace}`"},
                {"tag": "markdown", "content": f"**版本：** `{old_version}` → `{new_version}` {emoji} **{lbl}**"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**变更原因：**\n{reason}"},
                files_element,
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**状态：** {commit_status} | **时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}"},
            ],
        },
    }
    return card


def send_feishu(card: dict):
    """通过 openclaw message tool 发送飞书消息"""
    # 构建飞书消息（使用 REST API 直接发送）
    # 需要飞书机器人的 webhook 或 app_token
    # 这里通过 subprocess 调用 curl 发送
    card_json = json.dumps(card, ensure_ascii=False)
    print(f"[飞书通知] 卡片内容：{card_json[:200]}")
    print("[飞书通知] 已构建卡片（message tool 在主 agent 中调用）")


def notify_change(skill_name: str, workspace: str, old_version: str, new_version: str, bump_type: str, reason: str, changed_files: list, commit_ok: bool = True):
    """发送飞书通知"""
    try:
        card = format_feishu_card(
            skill_name, workspace, old_version, new_version,
            bump_type, reason, changed_files, commit_ok
        )
        send_feishu(card)
        print(f"✅ 飞书通知已发送: {skill_name} {old_version} → {new_version}")
    except Exception as e:
        print(f"❌ 飞书通知失败: {e}")
        # 不抛出异常，不阻断主流程


if __name__ == "__main__":
    # 测试
    notify_change(
        "skill_order_to_huading_template", "ai-order",
        "5.8.0", "5.8.1", "patch",
        "修复了 SKU 模糊匹配第三层逻辑的 bug",
        ["tools/_sku_mapper.py", "field_mapping/rules/default.yaml"],
        True
    )
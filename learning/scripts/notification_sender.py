#!/usr/bin/env python3
"""
notification_sender.py — 自学习通知发送器（双模式）

模式 1: Agent 模式（推荐）
  写入通知队列文件，由 OpenClaw agent heartbeat 检查并通过 message tool 发送。
  适用场景：improver.py / effect_tracker.py / daily_summary.py 等脚本。

模式 2: Webhook 模式（备用）
  通过 FEISHU_WEBHOOK / DINGTALK_ROBOT_WEBHOOK 直接发送。
  适用场景：agent 不在线时的降级方案。

通知类型（8 种）：
  1. alias_expansion     — 别名表扩充建议
  2. threshold_tuning    — 阈值调优建议
  3. keyword_update      — 关键词库更新建议
  4. cleaning_rule       — 清洗规则增强建议
  5. regression_warning  — 效果追踪回退预警
  6. improvement_report  — 完整改进报告
  7. ci_failure          — CI 验证失败
  8. daily_summary       — 每日别名汇总
"""
import os
import sys
import json
import time
import re
import yaml
from typing import List, Dict, Optional
from datetime import datetime


def _detect_workspace():
    env_ws = os.environ.get("AI_ORDER_WORKSPACE")
    if env_ws and os.path.isdir(env_ws):
        return env_ws
    script_dir = os.path.dirname(os.path.abspath(__file__))
    check = script_dir
    for _ in range(5):
        check = os.path.dirname(check)
        if os.path.isdir(os.path.join(check, "skills")):
            return check
    return os.getcwd()


_WORKSPACE = _detect_workspace()
_QUEUE_DIR = os.path.join(_WORKSPACE, "events", "notifications")
_CONFIG_PATH = os.path.join(_WORKSPACE, "learning", "config", "notification_config.yaml")

# 确保通知队列目录存在
os.makedirs(_QUEUE_DIR, exist_ok=True)


def _expand_env_vars(value: str) -> str:
    def _replace(match):
        var_name = match.group(1)
        default = match.group(3) or ""
        return os.environ.get(var_name, default)
    if isinstance(value, str):
        return re.sub(r'\$\{([^}:]+)(:-([^}]*))?\}', _replace, value)
    return value


def _load_config() -> Dict:
    if not os.path.exists(_CONFIG_PATH):
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return config
    except Exception:
        return {}


# ── 通知类型标题映射 ──────────────────────────────

_TYPE_TITLES = {
    "alias_expansion": "🔄 别名表扩充建议",
    "threshold_tuning": "🎯 阈值调优建议",
    "keyword_update": "🔑 关键词库更新建议",
    "cleaning_rule": "🧹 清洗规则增强建议",
    "regression_warning": "⚠️ 效果追踪回退预警",
    "improvement_report": "📋 自学习改进报告",
    "ci_failure": "❌ CI 验证失败",
    "daily_summary": "📊 每日别名汇总",
}

_TYPE_EMOJI = {
    "alias_expansion": "🔄",
    "threshold_tuning": "🎯",
    "keyword_update": "🔑",
    "cleaning_rule": "🧹",
    "regression_warning": "⚠️",
    "improvement_report": "📋",
    "ci_failure": "❌",
    "daily_summary": "📊",
}


# ── 核心：写入通知队列（Agent 模式）────────────────

def _enqueue_notification(notification_type: str, message: str,
                          title: str = None, priority: str = "normal") -> str:
    """
    将通知写入队列文件，等待 Agent heartbeat 拾取并发送。

    Returns:
        通知文件路径
    """
    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{notification_type}.json"
    filepath = os.path.join(_QUEUE_DIR, filename)

    payload = {
        "type": notification_type,
        "title": title or _TYPE_TITLES.get(notification_type, "AI建单助手通知"),
        "message": message,
        "priority": priority,  # "high" / "normal" / "low"
        "created_at": now.isoformat(),
        "status": "pending",
        "channels": ["auto"],  # auto = Agent 用当前绑定的通道发送（飞书/钉钉均可）
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[notification] ✅ 已入队: {filename}", flush=True)
    return filepath


def get_pending_notifications() -> List[Dict]:
    """获取所有待发送的通知（供 Agent heartbeat 调用）"""
    pending = []
    if not os.path.isdir(_QUEUE_DIR):
        return pending
    for filename in sorted(os.listdir(_QUEUE_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(_QUEUE_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") == "pending":
                data["_filepath"] = filepath
                pending.append(data)
        except Exception:
            continue
    return pending


def mark_sent(filepath: str):
    """标记通知为已发送"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["status"] = "sent"
        data["sent_at"] = datetime.now().isoformat()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[notification] mark_sent failed: {e}", flush=True)


# ── Webhook 备用模式 ──────────────────────────────

def _send_feishu_webhook(message: str, title: str = "") -> bool:
    import requests
    webhook = os.getenv("FEISHU_WEBHOOK")
    if not webhook:
        return False
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": f"📊 {title}"}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": message}]
        }
    }
    try:
        resp = requests.post(webhook, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _send_dingtalk_webhook(message: str, title: str = "") -> bool:
    import requests
    webhook = os.getenv("DINGTALK_ROBOT_WEBHOOK")
    if not webhook:
        return False
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": f"📊 {title}", "text": f"## {title}\n\n{message}"}
    }
    try:
        resp = requests.post(webhook, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


# ── 统一发送入口 ──────────────────────────────────

def send_notification(notification_type: str, message: str,
                      title: str = None, priority: str = "normal") -> bool:
    """
    发送通知。优先使用 Agent 队列模式，降级到 Webhook 模式。

    Returns:
        True = 至少一个通道发送/入队成功
    """
    title = title or _TYPE_TITLES.get(notification_type, "AI建单助手通知")

    # 模式 1: Agent 队列（总是写入，确保不丢）
    filepath = _enqueue_notification(notification_type, message, title, priority)

    # 模式 2: Webhook 备用（有配置时同时发送）
    config = _load_config()
    channels = config.get("channels", {})
    webhook_sent = False

    if channels.get("feishu", {}).get("enabled"):
        if _send_feishu_webhook(message, title):
            webhook_sent = True

    if channels.get("dingtalk", {}).get("enabled"):
        if _send_dingtalk_webhook(message, title):
            webhook_sent = True

    # Agent 队列总是成功的（文件写入）
    return True


# ── 便捷函数（各类型专用）────────────────────────

def notify_keyword_update(keywords: List[Dict]) -> bool:
    if not keywords:
        return False
    lines = [f"发现 **{len(keywords)}** 个高频未匹配关键词：\n"]
    for i, kw in enumerate(keywords[:10], 1):
        name = kw.get("keyword", "?")
        count = kw.get("count", 0)
        samples = kw.get("sample_names", [])
        sample_str = "、".join(str(s) for s in samples[:3]) if samples else "—"
        lines.append(f"{i}. **{name}** — 出现 {count} 次（示例：{sample_str}）")
    lines.append(f"\n> 回复「确认关键词」添加到词库 / 「跳过」忽略")
    return send_notification("keyword_update", "\n".join(lines))


def notify_cleaning_rule(rules: List[Dict]) -> bool:
    if not rules:
        return False
    lines = [f"发现 **{len(rules)}** 个清洗规则缺口：\n"]
    for i, r in enumerate(rules[:10], 1):
        original = r.get("original_name", "?")
        cleaned = r.get("cleaned_name", "?")
        count = r.get("count", 0)
        lines.append(f"{i}. `{original}` → `{cleaned}` — {count} 次")
    lines.append(f"\n> 回复「确认清洗」添加规则 / 「跳过」忽略")
    return send_notification("cleaning_rule", "\n".join(lines))


def notify_threshold_tuning(suggestions: List[Dict]) -> bool:
    if not suggestions:
        return False
    lines = [f"发现 **{len(suggestions)}** 个阈值调优建议：\n"]
    lines.append("| 类型 | 层 | 成功率 | 纠正率 | 建议 |")
    lines.append("|------|-----|--------|--------|------|")
    for s in suggestions[:10]:
        entity = s.get("entity_type", "?")
        layer = s.get("layer_name", "?")
        rate = s.get("success_rate", 0)
        corr = s.get("correction_rate", 0)
        suggested = s.get("suggested_threshold", "—")
        lines.append(f"| {entity} | {layer} | {rate:.0f}% | {corr:.0f}% | {suggested} |")
    lines.append(f"\n> 回复「确认阈值」应用 / 「跳过」忽略")
    return send_notification("threshold_tuning", "\n".join(lines))


def notify_alias_expansion(aliases: List[Dict]) -> bool:
    if not aliases:
        return False
    lines = [f"发现 **{len(aliases)}** 个高频 SKU 纠正：\n"]
    for i, a in enumerate(aliases[:10], 1):
        order_name = a.get("order_name", "?")
        system_name = a.get("system_name", "?")
        count = a.get("count", 0)
        lines.append(f"{i}. `{order_name}` → `{system_name}` — {count} 次")
    lines.append(f"\n> 回复「确认别名」添加到别名表 / 「跳过」忽略")
    return send_notification("alias_expansion", "\n".join(lines))


def notify_regression_warning(evaluations: List[Dict]) -> bool:
    regressions = [e for e in evaluations if e.get("verdict") == "regression"]
    if not regressions:
        return False
    lines = [f"**{len(regressions)}** 项变更导致指标回退：\n"]
    for e in regressions:
        change_id = e.get("change_id", "?")
        change_type = e.get("change_type", "?")
        deltas = e.get("deltas", {})
        sku_delta = deltas.get("sku_match_rate_delta", "?")
        if isinstance(sku_delta, (int, float)):
            lines.append(f"- 变更 #{change_id}（{change_type}）：SKU 匹配率 {sku_delta:+.1f}%")
        else:
            lines.append(f"- 变更 #{change_id}（{change_type}）：SKU 匹配率 {sku_delta}")
    lines.append(f"\n> 建议回滚这些变更，回复「回滚 #ID」操作")
    return send_notification("regression_warning", "\n".join(lines), priority="high")


def notify_improvement_report(report: str) -> bool:
    return send_notification("improvement_report", report)


def notify_ci_failure(ci_result: Dict, suggestions_summary: str = "") -> bool:
    msg = f"CI 回归测试未通过，**不自动应用变更**。\n\n"
    if suggestions_summary:
        msg += f"待处理建议：{suggestions_summary}\n\n"
    errors = ci_result.get("errors", [])
    if errors:
        msg += "失败项：\n"
        for err in errors[:5]:
            msg += f"- {err}\n"
    msg += f"\n> 请检查后手动决定是否应用"
    return send_notification("ci_failure", msg, priority="high")


# ── CLI 入口 ──────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python notification_sender.py <type> <message>")
        print(f"Types: {', '.join(_TYPE_TITLES.keys())}")
        print(f"\nQueue dir: {_QUEUE_DIR}")
        pending = get_pending_notifications()
        if pending:
            print(f"Pending: {len(pending)} notifications")
        sys.exit(1)

    ntype = sys.argv[1]
    message = sys.argv[2]

    success = send_notification(ntype, message)
    print(f"Notification queued: {success}")
    sys.exit(0 if success else 1)

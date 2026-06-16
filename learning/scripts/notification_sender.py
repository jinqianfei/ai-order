#!/usr/bin/env python3
"""
自学习模块 — 通知发送脚本（飞书 + 钉钉双通道）

支持 8 种通知类型：
  1. alias_expansion     — 别名表扩充建议
  2. threshold_tuning    — 阈值调优建议
  3. keyword_update      — 关键词库更新建议
  4. cleaning_rule       — 清洗规则增强建议
  5. regression_warning  — 效果追踪回退预警
  6. improvement_report  — 完整改进报告
  7. ci_failure          — CI 验证失败
  8. daily_summary       — 每日别名汇总

用法：
    from notification_sender import send_notification
    send_notification("keyword_update", "发现 5 个高频关键词...")

    # CLI
    python3 notification_sender.py keyword_update "消息内容"
"""
import os
import sys
import yaml
import re
import requests
from typing import List, Dict, Optional


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
if _WORKSPACE not in sys.path:
    sys.path.insert(0, _WORKSPACE)

_CONFIG_PATH = os.path.join(_WORKSPACE, "learning", "config", "notification_config.yaml")


def _expand_env_vars(value: str) -> str:
    """展开 ${VAR:-default} 环境变量引用"""
    def _replace(match):
        var_name = match.group(1)
        default = match.group(3) or ""
        return os.environ.get(var_name, default)
    if isinstance(value, str):
        return re.sub(r'\$\{([^}:]+)(:-([^}]*))?\}', _replace, value)
    return value


def _load_config() -> Dict:
    """加载通知配置"""
    if not os.path.exists(_CONFIG_PATH):
        print(f"[notification] Config not found: {_CONFIG_PATH}", flush=True)
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        for user in config.get("users", []):
            if "user_id" in user:
                user["user_id"] = _expand_env_vars(user["user_id"])
        return config
    except Exception as e:
        print(f"[notification] Config load error: {e}", flush=True)
        return {}


def _get_recipients(config: Dict, notification_type: str) -> List[Dict]:
    """根据通知类型获取接收人"""
    approver_rules = config.get("approvers", {}).get(notification_type, [])
    recipients = []
    for rule in approver_rules:
        role = rule.get("role")
        for user in config.get("users", []):
            if user.get("role") == role:
                recipients.append(user)
    return recipients


# ── 飞书发送 ──────────────────────────────────────

def _send_feishu_webhook(message: str, title: str = "") -> bool:
    """飞书 webhook 发送（富文本卡片）"""
    webhook = os.getenv("FEISHU_WEBHOOK")
    if not webhook:
        print("[notification] FEISHU_WEBHOOK not set, skip", flush=True)
        return False

    # 飞书交互卡片（支持 Markdown）
    if title:
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"📊 {title}"},
                    "template": "blue"
                },
                "elements": [
                    {"tag": "markdown", "content": message}
                ]
            }
        }
    else:
        payload = {
            "msg_type": "text",
            "content": {"text": message}
        }

    try:
        resp = requests.post(webhook, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"[notification] ✅ 飞书发送成功", flush=True)
            return True
        else:
            print(f"[notification] ❌ 飞书发送失败: {resp.status_code}", flush=True)
            return False
    except Exception as e:
        print(f"[notification] ❌ 飞书发送异常: {e}", flush=True)
        return False


# ── 钉钉发送 ──────────────────────────────────────

def _send_dingtalk_webhook(message: str, title: str = "") -> bool:
    """钉钉 webhook 发送（Markdown 卡片）"""
    webhook = os.getenv("DINGTALK_ROBOT_WEBHOOK")
    if not webhook:
        print("[notification] DINGTALK_ROBOT_WEBHOOK not set, skip", flush=True)
        return False

    if title:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"📊 {title}",
                "text": f"## {title}\n\n{message}"
            }
        }
    else:
        payload = {
            "msgtype": "text",
            "text": {"content": message}
        }

    try:
        resp = requests.post(webhook, json=payload, timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            if result.get("errcode") == 0:
                print(f"[notification] ✅ 钉钉发送成功", flush=True)
                return True
            else:
                print(f"[notification] ❌ 钉钉返回错误: {result}", flush=True)
                return False
        else:
            print(f"[notification] ❌ 钉钉发送失败: {resp.status_code}", flush=True)
            return False
    except Exception as e:
        print(f"[notification] ❌ 钉钉发送异常: {e}", flush=True)
        return False


# ── 统一发送入口 ──────────────────────────────────

# 通知类型 → 标题映射
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


def send_notification(notification_type: str, message: str,
                      title: str = None) -> bool:
    """
    发送通知到所有启用的通道。

    Args:
        notification_type: 通知类型（8 种之一）
        message: 消息内容（支持 Markdown）
        title: 自定义标题（默认用类型映射）

    Returns:
        至少一个通道发送成功返回 True
    """
    config = _load_config()
    if not config:
        return False

    # 获取接收人（验证有人接收）
    recipients = _get_recipients(config, notification_type)
    if not recipients:
        print(f"[notification] No recipients for type: {notification_type}", flush=True)
        return False

    channels = config.get("channels", {})
    title = title or _TYPE_TITLES.get(notification_type, "AI建单助手通知")
    success_count = 0

    # 飞书通道
    if channels.get("feishu", {}).get("enabled"):
        if _send_feishu_webhook(message, title):
            success_count += 1

    # 钉钉通道
    if channels.get("dingtalk", {}).get("enabled"):
        if _send_dingtalk_webhook(message, title):
            success_count += 1

    return success_count > 0


# ── 便捷函数（各类型专用）────────────────────────

def notify_keyword_update(keywords: List[Dict]) -> bool:
    """发送关键词更新建议"""
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
    """发送清洗规则建议"""
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
    """发送阈值调优建议"""
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
    """发送别名表扩充建议"""
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
    """发送效果追踪回退预警"""
    regressions = [e for e in evaluations if e.get("verdict") == "regression"]
    if not regressions:
        return False
    lines = [f"⚠️ **{len(regressions)}** 项变更导致指标回退：\n"]
    for e in regressions:
        change_id = e.get("change_id", "?")
        change_type = e.get("change_type", "?")
        deltas = e.get("deltas", {})
        sku_delta = deltas.get("sku_match_rate_delta", "?")
        lines.append(f"- 变更 #{change_id}（{change_type}）：SKU 匹配率 {sku_delta:+.1f}%")
    lines.append(f"\n> 建议回滚这些变更，回复「回滚 #ID」操作")
    return send_notification("regression_warning", "\n".join(lines))


def notify_improvement_report(report: str) -> bool:
    """发送完整改进报告"""
    return send_notification("improvement_report", report)


def notify_ci_failure(ci_result: Dict, suggestions_summary: str = "") -> bool:
    """发送 CI 验证失败通知"""
    msg = f"CI 回归测试未通过，**不自动应用变更**。\n\n"
    if suggestions_summary:
        msg += f"待处理建议：{suggestions_summary}\n\n"
    errors = ci_result.get("errors", [])
    if errors:
        msg += "失败项：\n"
        for err in errors[:5]:
            msg += f"- {err}\n"
    msg += f"\n> 请检查后手动决定是否应用"
    return send_notification("ci_failure", msg)


# ── CLI 入口 ──────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python notification_sender.py <type> <message>")
        print(f"Types: {', '.join(_TYPE_TITLES.keys())}")
        sys.exit(1)

    ntype = sys.argv[1]
    message = sys.argv[2]

    success = send_notification(ntype, message)
    print(f"Notification sent: {success}")
    sys.exit(0 if success else 1)

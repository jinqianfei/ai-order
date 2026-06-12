#!/usr/bin/env python3
"""
learning/improver.py — 自学习改进执行器

职责：
1. 从 order_corrections 表读取高频纠正记录
2. 生成别名表候选条目
3. 推送审批通知（调用 notification_sender）
4. 人工确认后，写入 sku_aliases_auto.yaml / field_aliases_auto.yaml

闭环位置：
  分析(analyze_data.py) → 改进(improver.py) → 写入yaml → Skill读取 → 下次匹配更准
"""

import os
import sys
import datetime
import yaml
from typing import List, Dict, Optional

# ── 自动检测工作区 ──
def _detect_workspace():
    env_ws = os.environ.get("AI_ORDER_WORKSPACE")
    if env_ws and os.path.isdir(env_ws):
        return env_ws
    script_dir = os.path.dirname(os.path.abspath(__file__))
    check = script_dir
    for _ in range(6):
        check = os.path.dirname(check)
        if os.path.isdir(os.path.join(check, "skills")):
            return check
    return os.getcwd()

_WORKSPACE = _detect_workspace()
_SKILL_RULES_DIR = os.path.join(
    _WORKSPACE, "skills", "skill_order_to_huading_template", "field_mapping", "rules"
)

# yaml 文件路径
SKU_ALIASES_YAML = os.path.join(_SKILL_RULES_DIR, "sku_aliases_auto.yaml")
FIELD_ALIASES_YAML = os.path.join(_SKILL_RULES_DIR, "field_aliases_auto.yaml")

# 数据库依赖
try:
    from db.connection import get_default_db_config
    import psycopg2
except ImportError:
    get_default_db_config = None
    psycopg2 = None


def _get_db_connection():
    """获取数据库连接，失败返回 None"""
    if not get_default_db_config or not psycopg2:
        print("[improver] psycopg2 or db.connection not available", flush=True)
        return None
    try:
        config = get_default_db_config()
        return psycopg2.connect(**config)
    except Exception as e:
        print(f"[improver] DB connect failed: {e}", flush=True)
        return None


def _load_existing_aliases(yaml_path: str) -> List[Dict]:
    """读取现有 yaml 别名文件，返回别名列表"""
    if not os.path.exists(yaml_path):
        return []
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("aliases", []) or []
    except Exception as e:
        print(f"[improver] Failed to load {yaml_path}: {e}", flush=True)
        return []


def _make_alias_key(order_name: str, shipper_id: str) -> str:
    """生成去重 key"""
    return f"{order_name.strip().lower()}||{shipper_id.strip()}"


def generate_alias_suggestions(lookback_days: int = 7, min_count: int = 3) -> List[Dict]:
    """
    从 order_corrections 表查询高频 sku 纠正记录，生成别名候选。

    Args:
        lookback_days: 回溯天数
        min_count: 最少纠正次数

    Returns:
        候选列表 [{"order_name", "system_name", "count", "shipper_id"}]
    """
    conn = _get_db_connection()
    if not conn:
        print("[improver] No DB connection, returning empty suggestions", flush=True)
        return []

    try:
        cur = conn.cursor()
        query = """
            SELECT
                oc.entity_name,
                oc.corrected_value,
                COUNT(*) AS cnt
            FROM order_corrections oc
            WHERE oc.correction_type = 'sku'
              AND oc.created_at >= NOW() - make_interval(days => %s)
            GROUP BY oc.entity_name, oc.corrected_value
            HAVING COUNT(*) >= %s
            ORDER BY cnt DESC
        """
        cur.execute(query, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[improver] Query failed: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return []

    # 加载现有别名用于去重
    existing = _load_existing_aliases(SKU_ALIASES_YAML)
    existing_keys = {
        _make_alias_key(a.get("order_product_name", ""), a.get("shipper_id", ""))
        for a in existing
    }

    suggestions = []
    for entity_name, corrected_value, cnt in rows:
        # 获取 shipper_id（通过 order_feedback 关联）
        shipper_id = _get_shipper_id_for_correction(entity_name)
        if not shipper_id:
            continue

        key = _make_alias_key(entity_name, shipper_id)
        if key in existing_keys:
            continue  # 已存在，跳过

        suggestions.append({
            "order_name": entity_name,
            "system_name": corrected_value,
            "count": cnt,
            "shipper_id": shipper_id,
        })
        existing_keys.add(key)  # 防止本次结果内重复

    return suggestions


def _get_shipper_id_for_correction(entity_name: str) -> Optional[str]:
    """通过 order_feedback 获取 entity_name 对应的 shipper_id (owner_code)"""
    conn = _get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT of.owner_code
            FROM order_feedback of_
            JOIN order_corrections oc ON oc.feedback_id = of_.id
            WHERE oc.entity_name = %s
            LIMIT 1
        """, (entity_name,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"[improver] shipper_id lookup failed: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return None


def notify_suggestions(suggestions: List[Dict]) -> bool:
    """
    格式化建议并推送飞书通知。

    Returns:
        是否发送成功
    """
    if not suggestions:
        return True

    today = datetime.date.today().isoformat()
    lines = [f"📋 别名表改进建议 ({today})\n"]
    lines.append("| 订单商品名 | 系统商品名 | 纠正次数 |")
    lines.append("|-----------|-----------|---------|")
    for s in suggestions:
        lines.append(f"| {s['order_name']} | {s['system_name']} | {s['count']} |")
    lines.append("")
    lines.append("→ 回复「确认添加」执行 / 「跳过」忽略")

    message = "\n".join(lines)

    # 调用 notification_sender（作为模块导入）
    try:
        scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from notification_sender import send_notification
        return send_notification("alias_expansion", message)
    except ImportError as e:
        print(f"[improver] notification_sender import failed: {e}", flush=True)
        print(f"[improver] Notification content:\n{message}", flush=True)
        return False
    except Exception as e:
        print(f"[improver] Notification send failed: {e}", flush=True)
        return False


def apply_suggestions(suggestions: List[Dict], yaml_path: str = None) -> int:
    """
    将建议写入 sku_aliases_auto.yaml。

    Args:
        suggestions: 建议列表
        yaml_path: yaml 文件路径，默认使用 SKU_ALIASES_YAML

    Returns:
        新增条目数
    """
    yaml_path = yaml_path or SKU_ALIASES_YAML

    # 确保目录存在
    os.makedirs(os.path.dirname(yaml_path), exist_ok=True)

    # 读取现有
    existing = _load_existing_aliases(yaml_path)
    existing_keys = {
        _make_alias_key(a.get("order_product_name", ""), a.get("shipper_id", ""))
        for a in existing
    }

    today = datetime.date.today().isoformat()
    added = 0
    for s in suggestions:
        key = _make_alias_key(s["order_name"], s["shipper_id"])
        if key in existing_keys:
            continue  # 去重

        existing.append({
            "order_product_name": s["order_name"],
            "system_product_name": s["system_name"],
            "shipper_id": s["shipper_id"],
            "source": "auto",
            "correction_count": s["count"],
            "confirmed_at": today,
        })
        existing_keys.add(key)
        added += 1

    if added == 0:
        print("[improver] No new entries to add", flush=True)
        return 0

    # 写入
    try:
        data = {"aliases": existing}
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"[improver] Added {added} entries to {yaml_path}", flush=True)
        return added
    except Exception as e:
        print(f"[improver] YAML write failed: {e}", flush=True)
        return 0


def run_improvement_cycle(auto_apply: bool = False) -> Dict:
    """
    主入口：执行一次完整改进循环。

    Args:
        auto_apply: True=直接写入 yaml；False=仅通知，等人工确认

    Returns:
        {"suggestions_count": int, "applied": int, "notified": bool}
    """
    print("[improver] Starting improvement cycle...", flush=True)

    suggestions = generate_alias_suggestions()
    result = {"suggestions_count": len(suggestions), "applied": 0, "notified": False}

    if not suggestions:
        print("[improver] 暂无改进建议", flush=True)
        return result

    print(f"[improver] Found {len(suggestions)} suggestions", flush=True)

    # 推送通知
    notified = notify_suggestions(suggestions)
    result["notified"] = notified

    # 自动应用 or 等待人工确认
    if auto_apply:
        applied = apply_suggestions(suggestions)
        result["applied"] = applied
        print(f"[improver] Auto-applied {applied} entries", flush=True)
    else:
        print("[improver] Suggestions notified, waiting for manual confirmation", flush=True)

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="自学习改进执行器")
    parser.add_argument("--auto-apply", action="store_true", help="直接写入 yaml，不等人工确认")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--min-count", type=int, default=3)
    args = parser.parse_args()

    result = run_improvement_cycle(auto_apply=args.auto_apply)
    print(f"\n结果: {result}")

#!/usr/bin/env python3
"""
learning/effect_tracker.py — 自学习效果追踪模块

职责：
1. 记录每次改进实施（applied_changes 表）
2. 对比实施前后的关键指标（匹配率/纠正率/处理时长）
3. 生成效果报告（实施是否有效）
4. 在 run_improvement_cycle 中自动调用，追踪上一次的变更效果

闭环位置：
  ⑥ 实施 → ⑦ 追踪 → 回到 ①（飞轮转动）

数据流：
  improver.py.apply_*() → effect_tracker.record_change()
  → 下次 run_improvement_cycle() → effect_tracker.evaluate_changes()
  → 生成效果报告 → 附在改进报告中
"""

import os
import sys
import json
import datetime
from typing import Dict, List, Optional, Tuple

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

# 将 skill 根目录加入 sys.path（db.connection 在那里）
_SKILL_ROOT = os.path.join(_WORKSPACE, "skills", "skill_order_to_huading_template")
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

# 效果报告输出路径
EFFECT_REPORT_PATH = os.path.join("/tmp", "effect_tracker_report_{date}.md")

# DB 依赖
try:
    from db.connection import get_default_db_config
    import psycopg2
except ImportError:
    get_default_db_config = None
    psycopg2 = None


def _get_conn():
    if not get_default_db_config or not psycopg2:
        return None
    try:
        return psycopg2.connect(**get_default_db_config())
    except Exception:
        return None


# ════════════════════════════════════════════════════════════
# 数据库表（自动建表）
# ════════════════════════════════════════════════════════════

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS applied_changes (
    id SERIAL PRIMARY KEY,
    change_type TEXT NOT NULL CHECK (change_type IN (
        'sku_alias', 'field_alias', 'threshold', 'keyword', 'cleaning_rule'
    )),
    change_detail JSONB NOT NULL DEFAULT '{}',
    applied_at TIMESTAMP DEFAULT NOW(),
    effective_from DATE DEFAULT CURRENT_DATE,
    evaluate_after_days INT DEFAULT 7,
    evaluated BOOLEAN DEFAULT FALSE,
    evaluation_result JSONB DEFAULT '{}',
    evaluated_at TIMESTAMP,
    notes TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_applied_changes_type ON applied_changes(change_type);
CREATE INDEX IF NOT EXISTS idx_applied_changes_eval ON applied_changes(evaluated);
CREATE INDEX IF NOT EXISTS idx_applied_changes_date ON applied_changes(applied_at DESC);
"""


def ensure_schema():
    """确保 applied_changes 表存在"""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(_SCHEMA_SQL)
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[effect_tracker] schema ensure failed: {e}", flush=True)
        conn.rollback()
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 记录变更
# ════════════════════════════════════════════════════════════

def record_change(change_type: str, change_detail: Dict,
                  evaluate_after_days: int = 7) -> Optional[int]:
    """
    记录一次改进实施。

    Args:
        change_type: 'sku_alias' / 'field_alias' / 'threshold' / 'keyword' / 'cleaning_rule'
        change_detail: 变更详情 dict
        evaluate_after_days: N 天后评估效果

    Returns:
        change_id 或 None
    """
    ensure_schema()
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO applied_changes (change_type, change_detail, evaluate_after_days)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (change_type, json.dumps(change_detail, ensure_ascii=False), evaluate_after_days))
        change_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        print(f"[effect_tracker] Recorded change #{change_id} ({change_type})", flush=True)
        return change_id
    except Exception as e:
        print(f"[effect_tracker] record_change failed: {e}", flush=True)
        conn.rollback()
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def record_batch_changes(change_type: str, changes: List[Dict],
                         evaluate_after_days: int = 7) -> int:
    """批量记录变更，返回成功记录数"""
    count = 0
    for change in changes:
        cid = record_change(change_type, change, evaluate_after_days)
        if cid:
            count += 1
    return count


# ════════════════════════════════════════════════════════════
# 评估效果
# ════════════════════════════════════════════════════════════

def get_pending_evaluations() -> List[Dict]:
    """获取所有待评估的变更"""
    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, change_type, change_detail, applied_at, effective_from,
                   evaluate_after_days
            FROM applied_changes
            WHERE evaluated = FALSE
              AND CURRENT_DATE >= effective_from + evaluate_after_days
            ORDER BY applied_at ASC
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        print(f"[effect_tracker] get_pending_evaluations failed: {e}", flush=True)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _get_metrics_for_period(start_date: str, end_date: str) -> Dict:
    """获取指定日期范围的关键指标"""
    conn = _get_conn()
    if not conn:
        return {}
    try:
        cur = conn.cursor()

        # 订单级指标
        cur.execute("""
            SELECT
                COUNT(*) as total_orders,
                AVG(store_match_rate) as avg_store_rate,
                AVG(sku_match_rate) as avg_sku_rate,
                AVG(processing_time_ms) as avg_time_ms,
                SUM(CASE WHEN user_modified THEN 1 ELSE 0 END) as modified_count,
                SUM(CASE WHEN user_confirmed THEN 1 ELSE 0 END) as confirmed_count
            FROM order_feedback
            WHERE order_date >= %s AND order_date < %s
        """, (start_date, end_date))
        order_metrics = cur.fetchone()

        # 纠正数
        cur.execute("""
            SELECT COUNT(*) FROM order_corrections
            WHERE created_at >= %s AND created_at < %s
        """, (start_date, end_date))
        correction_count = cur.fetchone()[0]

        cur.close()
        return {
            "total_orders": order_metrics[0] or 0,
            "avg_store_match_rate": float(order_metrics[1] or 0),
            "avg_sku_match_rate": float(order_metrics[2] or 0),
            "avg_processing_time_ms": float(order_metrics[3] or 0),
            "modified_orders": order_metrics[4] or 0,
            "confirmed_orders": order_metrics[5] or 0,
            "correction_count": correction_count,
        }
    except Exception as e:
        print(f"[effect_tracker] _get_metrics_for_period failed: {e}", flush=True)
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _get_layer_metrics(entity_type: str, start_date: str, end_date: str) -> Dict:
    """获取指定实体类型的层成功率变化"""
    conn = _get_conn()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT layer_name, total_attempts, success_count,
                   user_corrected_count, success_rate, avg_match_score
            FROM layer_success_rate
            WHERE entity_type = %s
            ORDER BY layer_name
        """, (entity_type,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        return {r["layer_name"]: r for r in rows}
    except Exception as e:
        print(f"[effect_tracker] _get_layer_metrics failed: {e}", flush=True)
        return {}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def evaluate_single_change(change: Dict) -> Dict:
    """
    评估单个变更的效果。

    对比变更前后各 7 天的指标：
    - SKU 匹配率
    - 纠正数
    - 层成功率（受影响的层）
    """
    change_type = change["change_type"]
    applied_at = change["applied_at"]
    evaluate_days = change.get("evaluate_after_days", 7)

    # 计算前后时间段
    if isinstance(applied_at, str):
        applied_date = datetime.datetime.fromisoformat(applied_at.replace("Z", "+00:00")).date()
    elif isinstance(applied_at, datetime.datetime):
        applied_date = applied_at.date()
    else:
        applied_date = datetime.date.today()

    before_end = applied_date.isoformat()
    before_start = (applied_date - datetime.timedelta(days=evaluate_days)).isoformat()
    after_start = applied_date.isoformat()
    after_end = (applied_date + datetime.timedelta(days=evaluate_days)).isoformat()

    # 获取前后指标
    before_metrics = _get_metrics_for_period(before_start, before_end)
    after_metrics = _get_metrics_for_period(after_start, after_end)

    # 计算变化
    result = {
        "change_id": change["id"],
        "change_type": change_type,
        "applied_at": applied_date.isoformat(),
        "evaluation_period": {"before": f"{before_start}~{before_end}",
                               "after": f"{after_start}~{after_end}"},
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "deltas": {},
        "verdict": "unknown",
    }

    if before_metrics and after_metrics:
        deltas = {}
        # SKU 匹配率变化
        if before_metrics.get("avg_sku_match_rate") is not None:
            delta_sku = after_metrics["avg_sku_match_rate"] - before_metrics["avg_sku_match_rate"]
            deltas["sku_match_rate_delta"] = round(delta_sku * 100, 2)

        # 纠正数变化
        if before_metrics.get("correction_count") is not None:
            delta_corr = after_metrics["correction_count"] - before_metrics["correction_count"]
            deltas["correction_count_delta"] = delta_corr

        # 修改订单数变化
        if before_metrics.get("modified_orders") is not None:
            delta_mod = after_metrics["modified_orders"] - before_metrics["modified_orders"]
            deltas["modified_orders_delta"] = delta_mod

        result["deltas"] = deltas

        # 判断效果
        sku_improved = deltas.get("sku_match_rate_delta", 0) > 0
        corrections_decreased = deltas.get("correction_count_delta", 0) < 0
        modifications_decreased = deltas.get("modified_orders_delta", 0) < 0

        if sku_improved and (corrections_decreased or modifications_decreased):
            result["verdict"] = "effective"
        elif sku_improved or corrections_decreased:
            result["verdict"] = "partially_effective"
        elif deltas.get("sku_match_rate_delta", 0) < -5:
            result["verdict"] = "regression"
        elif before_metrics.get("total_orders", 0) == 0 and after_metrics.get("total_orders", 0) == 0:
            result["verdict"] = "insufficient_data"
        else:
            result["verdict"] = "neutral"

    return result


def evaluate_all_pending() -> List[Dict]:
    """评估所有待评估的变更，返回评估结果列表"""
    pending = get_pending_evaluations()
    if not pending:
        print("[effect_tracker] No pending evaluations", flush=True)
        return []

    results = []
    for change in pending:
        result = evaluate_single_change(change)
        results.append(result)

        # 标记为已评估
        _mark_evaluated(change["id"], result)

    print(f"[effect_tracker] Evaluated {len(results)} changes", flush=True)
    return results


def _mark_evaluated(change_id: int, result: Dict):
    """标记变更为已评估"""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE applied_changes
            SET evaluated = TRUE,
                evaluation_result = %s,
                evaluated_at = NOW()
            WHERE id = %s
        """, (json.dumps(result, ensure_ascii=False, default=str), change_id))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[effect_tracker] mark_evaluated failed: {e}", flush=True)
        conn.rollback()
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# 报告生成
# ════════════════════════════════════════════════════════════

def generate_effect_report(evaluations: List[Dict] = None) -> str:
    """
    生成效果追踪报告（Markdown）。

    Args:
        evaluations: 评估结果列表（None = 自动获取最近评估）
    """
    if evaluations is None:
        evaluations = evaluate_all_pending()

    today = datetime.date.today().isoformat()
    lines = [
        f"# 自学习效果追踪报告 — {today}",
        "",
        f"**评估数量**: {len(evaluations)}",
        "",
    ]

    if not evaluations:
        lines.append("*暂无待评估的改进项*\n")
        report = "\n".join(lines)
        _write_report(report, today)
        return report

    # 按 verdict 分类统计
    verdicts = {}
    for e in evaluations:
        v = e.get("verdict", "unknown")
        verdicts[v] = verdicts.get(v, 0) + 1

    lines.append("## 📊 总体评估\n")
    verdict_labels = {
        "effective": "✅ 有效",
        "partially_effective": "⚠️ 部分有效",
        "neutral": "➡️ 无明显变化",
        "regression": "❌ 回退",
        "insufficient_data": "❓ 数据不足",
        "unknown": "❓ 未知",
    }
    for v, count in sorted(verdicts.items(), key=lambda x: -x[1]):
        label = verdict_labels.get(v, v)
        lines.append(f"- {label}: {count} 项")
    lines.append("")

    # 逐项详情
    lines.append("## 📋 逐项详情\n")
    lines.append("| # | 变更类型 | 实施日期 | SKU匹配率Δ | 纠正数Δ | 效果判定 |")
    lines.append("|---|---------|---------|-----------|---------|---------|")

    for i, e in enumerate(evaluations, 1):
        deltas = e.get("deltas", {})
        sku_delta = deltas.get("sku_match_rate_delta", "—")
        corr_delta = deltas.get("correction_count_delta", "—")
        verdict_icon = verdict_labels.get(e.get("verdict"), "❓")

        if isinstance(sku_delta, (int, float)):
            sku_delta = f"{sku_delta:+.1f}%"
        if isinstance(corr_delta, (int, float)):
            corr_delta = f"{corr_delta:+d}"

        lines.append(
            f"| {i} | {e.get('change_type', '?')} | {e.get('applied_at', '?')} "
            f"| {sku_delta} | {corr_delta} | {verdict_icon} |"
        )

    lines.append("")

    # 回退预警
    regressions = [e for e in evaluations if e.get("verdict") == "regression"]
    if regressions:
        lines.append("\n## ⚠️ 回退预警\n")
        for e in regressions:
            lines.append(f"- **{e.get('change_type')}** (#{e.get('change_id')})："
                        f"SKU 匹配率下降 {e.get('deltas', {}).get('sku_match_rate_delta', '?')}%，"
                        f"建议回滚此变更")
        lines.append("")

    # 建议
    lines.append("\n## 💡 建议\n")
    effective = [e for e in evaluations if e.get("verdict") == "effective"]
    if effective:
        lines.append(f"- ✅ {len(effective)} 项变更有效，继续保持")
    partial = [e for e in evaluations if e.get("verdict") == "partially_effective"]
    if partial:
        lines.append(f"- ⚠️ {len(partial)} 项部分有效，可考虑进一步优化")
    if regressions:
        lines.append(f"- ❌ {len(regressions)} 项回退，建议回滚")
    lines.append("")

    report = "\n".join(lines)
    _write_report(report, today)
    return report


def _write_report(report: str, date_str: str):
    """写入报告文件"""
    output_path = EFFECT_REPORT_PATH.format(date=date_str)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[effect_tracker] Report written to {output_path}", flush=True)
    except Exception as e:
        print(f"[effect_tracker] report write failed: {e}", flush=True)


def get_recent_evaluations(limit: int = 10) -> List[Dict]:
    """获取最近的评估结果"""
    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, change_type, change_detail, applied_at,
                   evaluation_result, evaluated_at
            FROM applied_changes
            WHERE evaluated = TRUE
            ORDER BY evaluated_at DESC
            LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        print(f"[effect_tracker] get_recent_evaluations failed: {e}", flush=True)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="自学习效果追踪")
    parser.add_argument("--evaluate", action="store_true", help="评估所有待评估变更")
    parser.add_argument("--report", action="store_true", help="生成效果报告")
    parser.add_argument("--record", type=str, help="记录变更 (JSON string)")
    parser.add_argument("--type", type=str, default="sku_alias", help="变更类型")
    args = parser.parse_args()

    ensure_schema()

    if args.record:
        detail = json.loads(args.record)
        cid = record_change(args.type, detail)
        print(f"Recorded change #{cid}")
    elif args.evaluate:
        results = evaluate_all_pending()
        print(f"Evaluated {len(results)} changes")
        for r in results:
            print(f"  #{r['change_id']} ({r['change_type']}): {r['verdict']}")
    elif args.report:
        report = generate_effect_report()
        print(report)
    else:
        # 默认：评估 + 报告
        results = evaluate_all_pending()
        report = generate_effect_report(results)
        print(report)

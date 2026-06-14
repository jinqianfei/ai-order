#!/usr/bin/env python3
"""
自学习模块 — 分析脚本（v2.0 — 完整 6 项分析 + 3 项监控分析）

功能：
1. 高频纠正商品 → SKU 别名表候选（滚动 7 天，≥3 次）
2. 未知字段 → 字段别名候选（滚动 7 天，≥2 次）
3. 层成功率统计（累计全量，≥50 次尝试）
4. 阈值调优建议（滚动 30 天，纠正率排名 + 建议值）
5. 关键词词库更新候选（滚动 30 天，反复出现的未匹配关键词）
6. 清洗规则增强候选（滚动 30 天，反复导致未匹配的清洗缺口）
7. 纠正排名（30 天内，纠正类型 × 匹配层）
8. 纠正趋势（本周 vs 上周环比）
9. SKU vs 门店匹配分类统计

输出 Markdown 报告到 /tmp/analysis_report_YYYYMMDD.md

用法：
    python3 learning/scripts/analyze_data.py
"""
import os
import sys
import datetime
import json
import yaml

# ── 自动检测工作区（无硬编码路径）──
def _detect_workspace():
    env_ws = os.environ.get("AI_ORDER_WORKSPACE")
    if env_ws and os.path.isdir(env_ws):
        return env_ws
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for parent_dir in [script_dir] + [os.path.dirname(p) for p in [
        script_dir,
        os.path.dirname(script_dir),
    ]]:
        candidate = parent_dir if os.path.isdir(os.path.join(parent_dir, "skills")) else None
        if candidate:
            return candidate
    # 向上查找
    check = script_dir
    for _ in range(5):
        check = os.path.dirname(check)
        if os.path.isdir(os.path.join(check, "skills")):
            return check
    return os.getcwd()

_WORKSPACE = _detect_workspace()
_SKILL_ROOT = os.path.join(_WORKSPACE, "skills", "skill_order_to_huading_template")
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

# ── 加载分析阈值配置 ──
_ANALYSIS_CONFIG_PATH = os.path.join(_WORKSPACE, "learning", "config", "analysis_config.yaml")
_analysis_cfg = {}
if os.path.exists(_ANALYSIS_CONFIG_PATH):
    with open(_ANALYSIS_CONFIG_PATH, "r", encoding="utf-8") as f:
        _analysis_cfg = yaml.safe_load(f) or {}

try:
    from db.connection import get_default_db_config
    import psycopg2
except ImportError as e:
    print(f"[ERROR] Import failed: {e}")
    sys.exit(1)


def get_db_connection():
    """获取数据库连接"""
    try:
        config = get_default_db_config()
        return psycopg2.connect(**config)
    except Exception as e:
        print(f"[ERROR] DB connect failed: {e}")
        return None


# ════════════════════════════════════════════════════════════
# 分析函数 1：SKU 别名候选（已有）
# ════════════════════════════════════════════════════════════

def analyze_alias_candidates():
    """高频纠正 → SKU 别名表候选（参数从 analysis_config.yaml 读取）"""
    cfg = _analysis_cfg.get("alias_candidates", {})
    lookback_days = cfg.get("lookback_days", 7)
    min_count = cfg.get("min_correction_count", 3)
    max_results = cfg.get("max_results", 20)

    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT entity_name, corrected_value, COUNT(*) as cnt
            FROM order_corrections
            WHERE correction_type = 'sku'
              AND created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY entity_name, corrected_value
            HAVING COUNT(*) >= %s
            ORDER BY cnt DESC
            LIMIT %s
        """, (lookback_days, min_count, max_results))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[WARN] analyze_alias_candidates failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 分析函数 2：字段别名候选（新增 P1.1）
# ════════════════════════════════════════════════════════════

def analyze_field_alias_candidates():
    """
    未知字段 → 字段别名候选。
    数据来源：unknown_fields_log 表（由 parser.py emit unknown_field_detected 写入）
    逻辑：滚动 N 天，同一 (field_name, shipper_id) 出现 ≥ M 次 → 候选
    """
    cfg = _analysis_cfg.get("field_alias_candidates", {})
    lookback_days = cfg.get("lookback_days", 7)
    min_count = cfg.get("min_detection_count", 2)
    max_results = cfg.get("max_results", 20)

    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT field_name, shipper_id, COUNT(*) as cnt
            FROM unknown_fields_log
            WHERE detected_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY field_name, shipper_id
            HAVING COUNT(*) >= %s
            ORDER BY cnt DESC
            LIMIT %s
        """, (lookback_days, min_count, max_results))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[WARN] analyze_field_alias_candidates failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 分析函数 3：层成功率统计（已有）
# ════════════════════════════════════════════════════════════

def analyze_layer_success_rate():
    """层成功率统计（参数从 analysis_config.yaml 读取）"""
    cfg = _analysis_cfg.get("layer_success_rate", {})
    min_attempts = cfg.get("min_total_attempts", 50)

    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT entity_type, layer_name, total_attempts, success_count,
                   user_corrected_count,
                   ROUND(success_rate * 100, 2) as success_pct,
                   ROUND(avg_match_score, 4) as avg_score
            FROM layer_success_rate
            WHERE total_attempts >= %s
            ORDER BY entity_type, success_rate ASC
        """, (min_attempts,))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[WARN] analyze_layer_success_rate failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 分析函数 4：阈值调优建议（已有 + 增强：输出建议值）
# ════════════════════════════════════════════════════════════

def analyze_threshold_tuning():
    """阈值调优建议（参数从 analysis_config.yaml 读取）"""
    cfg = _analysis_cfg.get("threshold_tuning", {})
    lookback_days = cfg.get("lookback_days", 30)
    min_count = cfg.get("min_total_count", 10)
    rate_threshold = cfg.get("correction_rate_threshold", 30)

    conn = get_db_connection()
    if not conn:
        return [], rate_threshold
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT match_layer,
              COUNT(*) as total,
              SUM(CASE WHEN auto_matched THEN 1 ELSE 0 END) as confirmed,
              SUM(CASE WHEN NOT auto_matched THEN 1 ELSE 0 END) as corrected,
              ROUND((SUM(CASE WHEN NOT auto_matched THEN 1 ELSE 0 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100)::NUMERIC, 2) as correction_rate
            FROM order_corrections
            WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY match_layer
            HAVING COUNT(*) >= %s
            ORDER BY correction_rate DESC
        """, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        return rows, rate_threshold
    except Exception as e:
        print(f"[WARN] analyze_threshold_tuning failed: {e}")
        return [], rate_threshold
    finally:
        conn.close()


def generate_threshold_suggestions(threshold_data, rate_threshold):
    """
    基于阈值调优数据，生成具体的建议阈值变更。
    
    Returns:
        list of {layer, current_correction_rate, suggestion}
    """
    suggestions = []
    for row in threshold_data:
        layer, total, confirmed, corrected, correction_rate = row
        if float(correction_rate) > rate_threshold:
            # 纠正率超过阈值，建议降低匹配阈值
            suggestions.append({
                "layer": layer,
                "current_correction_rate": float(correction_rate),
                "total_samples": total,
                "suggestion": f"建议降低 {layer} 层的匹配阈值（当前纠正率 {correction_rate}% > {rate_threshold}%）",
                "risk": "medium"
            })
    return suggestions


# ════════════════════════════════════════════════════════════
# 分析函数 5：关键词词库更新候选（新增 P2.1）
# ════════════════════════════════════════════════════════════

def analyze_keyword_candidates():
    """
    关键词词库更新候选。
    数据来源：keyword_candidates_log 表（由 _sku_mapper.py emit unmatched_sku_keyword 写入）
    逻辑：滚动 N 天，某关键词在未匹配商品中反复出现 ≥ M 次 → 候选新关键词
    """
    cfg = _analysis_cfg.get("keyword_candidates", {})
    lookback_days = cfg.get("lookback_days", 30)
    min_count = cfg.get("min_keyword_count", 5)
    max_results = cfg.get("max_results", 20)

    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT extracted_keywords, COUNT(*) as cnt,
                   ARRAY_AGG(DISTINCT order_product_name) as sample_names
            FROM keyword_candidates_log
            WHERE detected_at >= CURRENT_DATE - INTERVAL '%s days'
              AND extracted_keywords IS NOT NULL
              AND extracted_keywords != ''
            GROUP BY extracted_keywords
            HAVING COUNT(*) >= %s
            ORDER BY cnt DESC
            LIMIT %s
        """, (lookback_days, min_count, max_results))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[WARN] analyze_keyword_candidates failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 分析函数 6：清洗规则增强候选（新增 P2.2）
# ════════════════════════════════════════════════════════════

def analyze_cleaning_rule_candidates():
    """
    清洗规则增强候选。
    数据来源：cleaning_rule_gap_log 表（由 _sku_mapper.py emit cleaning_rule_gap 写入）
    逻辑：滚动 N 天，某类清洗缺口反复出现 ≥ M 次 → 候选新清洗规则
    """
    cfg = _analysis_cfg.get("cleaning_rule_candidates", {})
    lookback_days = cfg.get("lookback_days", 30)
    min_count = cfg.get("min_gap_count", 3)
    max_results = cfg.get("max_results", 20)

    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT original_name, cleaned_name, COUNT(*) as cnt
            FROM cleaning_rule_gap_log
            WHERE detected_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY original_name, cleaned_name
            HAVING COUNT(*) >= %s
            ORDER BY cnt DESC
            LIMIT %s
        """, (lookback_days, min_count, max_results))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[WARN] analyze_cleaning_rule_candidates failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 分析函数 7：纠正排名（新增 P1.3）
# ════════════════════════════════════════════════════════════

def analyze_correction_ranking():
    """
    纠正类型 × 匹配层 排名分析。
    数据来源：order_corrections 表
    逻辑：滚动 N 天内，按 (correction_type, match_layer) 分组排序
    """
    cfg = _analysis_cfg.get("correction_ranking", {})
    lookback_days = cfg.get("lookback_days", 30)
    max_results = cfg.get("max_results", 20)

    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT correction_type, match_layer, COUNT(*) as cnt,
                   ROUND(AVG(match_score)::NUMERIC, 4) as avg_score
            FROM order_corrections
            WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY correction_type, match_layer
            ORDER BY cnt DESC
            LIMIT %s
        """, (lookback_days, max_results))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[WARN] analyze_correction_ranking failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 分析函数 8：纠正趋势（新增 P1.3）
# ════════════════════════════════════════════════════════════

def analyze_correction_trend():
    """
    纠正趋势分析（本周 vs 上周环比）。
    数据来源：order_corrections 表
    """
    cfg = _analysis_cfg.get("correction_trend", {})
    lookback_days = cfg.get("lookback_days", 14)

    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH this_week AS (
                SELECT correction_type, COUNT(*) as cnt
                FROM order_corrections
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY correction_type
            ),
            last_week AS (
                SELECT correction_type, COUNT(*) as cnt
                FROM order_corrections
                WHERE created_at >= CURRENT_DATE - INTERVAL '14 days'
                  AND created_at < CURRENT_DATE - INTERVAL '7 days'
                GROUP BY correction_type
            )
            SELECT
                COALESCE(t.correction_type, l.correction_type) as type,
                COALESCE(l.cnt, 0) as last_week,
                COALESCE(t.cnt, 0) as this_week,
                COALESCE(t.cnt, 0) - COALESCE(l.cnt, 0) as delta,
                CASE
                    WHEN COALESCE(l.cnt, 0) = 0 AND COALESCE(t.cnt, 0) > 0 THEN '新增'
                    WHEN COALESCE(l.cnt, 0) = 0 AND COALESCE(t.cnt, 0) = 0 THEN '无变化'
                    WHEN COALESCE(t.cnt, 0) > COALESCE(l.cnt, 0) THEN '上升'
                    WHEN COALESCE(t.cnt, 0) < COALESCE(l.cnt, 0) THEN '下降'
                    ELSE '持平'
                END as trend
            FROM this_week t
            FULL OUTER JOIN last_week l ON t.correction_type = l.correction_type
            ORDER BY ABS(COALESCE(t.cnt, 0) - COALESCE(l.cnt, 0)) DESC
        """)
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        print(f"[WARN] analyze_correction_trend failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 分析函数 9：SKU vs 门店匹配分类统计（新增 P1.3）
# ════════════════════════════════════════════════════════════

def analyze_sku_vs_store():
    """
    SKU 匹配 vs 门店匹配 分类统计。
    数据来源：layer_success_rate 表，按 entity_type 分组
    """
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                entity_type,
                SUM(total_attempts) as total,
                SUM(success_count) as successes,
                SUM(user_corrected_count) as corrections,
                ROUND(AVG(success_rate) * 100, 2) as avg_success_pct,
                ROUND(AVG(avg_match_score), 4) as avg_score
            FROM layer_success_rate
            GROUP BY entity_type
            ORDER BY avg_success_pct ASC
        """)
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "entity_type": r[0],
                "total": r[1],
                "successes": r[2],
                "corrections": r[3],
                "avg_success_pct": r[4],
                "avg_score": r[5]
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[WARN] analyze_sku_vs_store failed: {e}")
        return []
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# 报告生成（扩展为 9 个 Section）
# ════════════════════════════════════════════════════════════

def generate_report():
    """生成 Markdown 报告（v2.0 — 9 个分析维度）"""
    today = datetime.date.today().strftime("%Y%m%d")
    output_path = f"/tmp/analysis_report_{today}.md"

    lines = []
    lines.append(f"# 自学习模块分析报告 v2.0（{datetime.date.today()}）\n")

    has_content = False

    # ── Section 1: SKU 别名候选 ──
    lines.append("## 1. SKU 别名改进候选（近 7 天高频纠正）\n")
    alias_candidates = analyze_alias_candidates()
    if alias_candidates:
        has_content = True
        lines.append("| 订单商品名 | 正确 SKU 名 | 纠正次数 |")
        lines.append("|-----------|------------|---------|")
        for r in alias_candidates:
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} |")
    else:
        lines.append("*暂无数据（需要积累订单数据）*\n")

    # ── Section 2: 字段别名候选 ──
    lines.append("\n## 2. 字段别名候选（近 7 天高频未知字段）\n")
    field_candidates = analyze_field_alias_candidates()
    if field_candidates:
        has_content = True
        lines.append("| 未知字段名 | 货主ID | 出现次数 | 建议标准字段 |")
        lines.append("|-----------|--------|---------|-------------|")
        for r in field_candidates:
            field_name, shipper_id, cnt = r
            # 简单的字段名映射建议
            suggested = _suggest_standard_field(field_name)
            lines.append(f"| {field_name} | {shipper_id or '通用'} | {cnt} | {suggested} |")
        lines.append("\n*建议：将高频未知字段添加到 field_aliases_auto.yaml*")
    else:
        lines.append("*暂无数据*\n")

    # ── Section 3: 层成功率 ──
    lines.append("\n## 3. 层成功率统计（累计，≥50 次尝试）\n")
    layer_stats = analyze_layer_success_rate()
    if layer_stats:
        has_content = True
        lines.append("| 实体类型 | 层名 | 尝试次数 | 成功数 | 纠正数 | 成功率% | 平均匹配分 |")
        lines.append("|---------|------|---------|-------|-------|--------|-----------|")
        for r in layer_stats:
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |")
    else:
        lines.append("*暂无数据（需要积累订单数据）*\n")

    # ── Section 4: 阈值调优建议 ──
    threshold_cfg = _analysis_cfg.get("threshold_tuning", {})
    lookback_days = threshold_cfg.get("lookback_days", 30)
    rate_threshold = threshold_cfg.get("correction_rate_threshold", 30)
    lines.append(f"\n## 4. 阈值调优建议（近 {lookback_days} 天，纠正率排名）\n")
    threshold_data, rate_threshold = analyze_threshold_tuning()
    if threshold_data:
        has_content = True
        lines.append("| 匹配层 | 总次数 | 确认数 | 纠正数 | 纠正率% |")
        lines.append("|-------|-------|-------|-------|--------|")
        for r in threshold_data:
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |")

        # 生成建议
        suggestions = generate_threshold_suggestions(threshold_data, rate_threshold)
        if suggestions:
            lines.append("\n### 建议操作\n")
            for s in suggestions:
                lines.append(f"- ⚠️ **{s['layer']}**：{s['suggestion']}（样本量: {s['total_samples']}，风险: {s['risk']}）")
            lines.append("\n*建议变更前需先跑 CI 回归 + 历史订单回放验证*")
        else:
            lines.append(f"\n*所有层的纠正率均 ≤ {rate_threshold}%，无需调整*")
    else:
        lines.append("*暂无数据（需要积累订单数据）*\n")

    # ── Section 5: 关键词词库候选 ──
    lines.append("\n## 5. 关键词词库更新候选（近 30 天反复出现的未匹配关键词）\n")
    keyword_candidates = analyze_keyword_candidates()
    if keyword_candidates:
        has_content = True
        lines.append("| 关键词 | 出现次数 | 示例商品名 |")
        lines.append("|-------|---------|-----------|")
        for r in keyword_candidates:
            keywords, cnt, sample_names = r
            samples = ", ".join(sample_names[:3]) if sample_names else "-"
            lines.append(f"| {keywords} | {cnt} | {samples} |")
        lines.append("\n*建议：将高频关键词添加到 _sku_mapper.py 的 product_types / flavor_types*")
    else:
        lines.append("*暂无数据*\n")

    # ── Section 6: 清洗规则候选 ──
    lines.append("\n## 6. 清洗规则增强候选（近 30 天反复出现的清洗缺口）\n")
    cleaning_candidates = analyze_cleaning_rule_candidates()
    if cleaning_candidates:
        has_content = True
        lines.append("| 原始商品名 | 清洗后 | 出现次数 |")
        lines.append("|-----------|--------|---------|")
        for r in cleaning_candidates:
            lines.append(f"| {r[0]} | {r[1]} | {r[2]} |")
        lines.append("\n*建议：检查 _clean_product_name 的正则规则是否需要增强*")
    else:
        lines.append("*暂无数据*\n")

    # ── Section 7: 纠正排名 ──
    lines.append("\n## 7. 纠正排名（近 30 天，按纠正次数排序）\n")
    correction_ranking = analyze_correction_ranking()
    if correction_ranking:
        has_content = True
        lines.append("| 纠正类型 | 匹配层 | 纠正次数 | 平均匹配分 |")
        lines.append("|---------|--------|---------|-----------|")
        for r in correction_ranking:
            lines.append(f"| {r[0]} | {r[1] or '-'} | {r[2]} | {r[3] or '-'} |")
        # 给出洞察
        if correction_ranking:
            top = correction_ranking[0]
            lines.append(f"\n*🔍 洞察：纠正最多的类型是 **{top[0]}**（{top[1] or '-'} 层），共 {top[2]} 次*")
    else:
        lines.append("*暂无数据*\n")

    # ── Section 8: 纠正趋势 ──
    lines.append("\n## 8. 纠正趋势（本周 vs 上周环比）\n")
    trend_data = analyze_correction_trend()
    if trend_data:
        has_content = True
        lines.append("| 纠正类型 | 上周 | 本周 | 变化 | 趋势 |")
        lines.append("|---------|------|------|------|------|")
        for r in trend_data:
            type_name, last_w, this_w, delta, trend = r
            trend_icon = {"上升": "📈", "下降": "📉", "新增": "🆕", "持平": "➡️", "无变化": "➡️"}.get(trend, "❓")
            lines.append(f"| {type_name} | {last_w} | {this_w} | {delta:+d} | {trend_icon} {trend} |")
        # 给出洞察
        rising = [r for r in trend_data if r[4] == "上升"]
        if rising:
            lines.append(f"\n*⚠️ 注意：{len(rising)} 种纠正类型呈上升趋势，需关注*")
        declining = [r for r in trend_data if r[4] == "下降"]
        if declining:
            lines.append(f"\n*✅ 好消息：{len(declining)} 种纠正类型呈下降趋势*")
    else:
        lines.append("*暂无数据*\n")

    # ── Section 9: SKU vs 门店分类 ──
    lines.append("\n## 9. SKU 匹配 vs 门店匹配 分类统计\n")
    sku_vs_store = analyze_sku_vs_store()
    if sku_vs_store:
        has_content = True
        lines.append("| 实体类型 | 总尝试 | 成功数 | 纠正数 | 平均成功率% | 平均匹配分 |")
        lines.append("|---------|--------|--------|--------|-----------|-----------|")
        for r in sku_vs_store:
            lines.append(f"| {r['entity_type']} | {r['total']} | {r['successes']} | {r['corrections']} | {r['avg_success_pct']} | {r['avg_score']} |")
        # 给出洞察
        worst = min(sku_vs_store, key=lambda x: float(x['avg_success_pct'] or 0))
        lines.append(f"\n*🔍 洞察：成功率最低的实体类型是 **{worst['entity_type']}**（{worst['avg_success_pct']}%）*")
    else:
        lines.append("*暂无数据*\n")

    # ── 写入文件 ──
    report = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"分析报告已写入: {output_path}")

    # 有实质内容时自动发送飞书通知
    if has_content:
        try:
            _script_dir = os.path.dirname(os.path.abspath(__file__))
            if _script_dir not in sys.path:
                sys.path.insert(0, _script_dir)
            from notification_sender import send_notification
            send_notification("threshold_tuning", report)
        except Exception as e:
            print(f"[WARN] notification send failed: {e}")

    return output_path


def _suggest_standard_field(raw_field_name: str) -> str:
    """
    简单的字段名 → 标准字段名映射建议。
    基于常见的字段名模式做启发式匹配。
    """
    raw_lower = raw_field_name.strip().lower()

    # 门店相关
    store_keywords = ["门店", "店铺", "店名", "收货点", "配送点", "配送地址", "收货地址"]
    if any(k in raw_lower for k in store_keywords):
        return "store_name"

    # 商品相关
    product_keywords = ["商品", "产品", "品名", "货品", "物品", "货物"]
    if any(k in raw_lower for k in product_keywords):
        return "product_name"

    # 数量相关
    qty_keywords = ["数量", "数目", "个数", "件数"]
    if any(k in raw_lower for k in qty_keywords):
        return "quantity"

    # 规格相关
    spec_keywords = ["规格", "包装", "尺寸"]
    if any(k in raw_lower for k in spec_keywords):
        return "product_spec"

    # 单位相关
    unit_keywords = ["单位", "计量"]
    if any(k in raw_lower for k in unit_keywords):
        return "unit"

    # 地址相关
    addr_keywords = ["地址", "详细地址", "收货地址"]
    if any(k in raw_lower for k in addr_keywords):
        return "address"

    # 联系人/电话
    if any(k in raw_lower for k in ["联系", "收货人", "收件人"]):
        return "contact_person"
    if any(k in raw_lower for k in ["电话", "手机", "联系号码"]):
        return "phone"

    return "待人工确认"


if __name__ == "__main__":
    generate_report()

#!/usr/bin/env python3
"""
learning/improver.py — 自学习改进执行器（v2.0 — 完整闭环）

职责：
1. 从 order_corrections / unknown_fields_log / keyword_candidates_log / cleaning_rule_gap_log 读取数据
2. 生成 5 类改进建议：SKU别名 / 字段别名 / 阈值调优 / 关键词词库 / 清洗规则
3. **建议前先跑 CI 验证**（ci_regression + history_replay + accuracy_comparison）
4. 推送完整报告（建议 + CI结果 + 准确率对比）给审批人
5. 人工确认后，写入对应的 yaml / 配置文件
6. 集成 decider 迭代决策引擎

闭环位置：
  分析(analyze_data.py) → 建议(improver.py) → CI验证 → 审批 → 实施 → 效果追踪
"""

import os
import sys
import json
import subprocess
import datetime
import yaml
from typing import List, Dict, Optional, Tuple

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
_SKILL_ROOT = os.path.join(
    _WORKSPACE, "skills", "skill_order_to_huading_template"
)
_SKILL_RULES_DIR = os.path.join(_SKILL_ROOT, "field_mapping", "rules")
_SKILL_SCRIPTS_DIR = os.path.join(_SKILL_ROOT, "scripts")
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)
if _WORKSPACE not in sys.path:
    sys.path.insert(0, _WORKSPACE)

# yaml 文件路径
SKU_ALIASES_YAML = os.path.join(_SKILL_RULES_DIR, "sku_aliases_auto.yaml")
FIELD_ALIASES_YAML = os.path.join(_SKILL_RULES_DIR, "field_aliases_auto.yaml")

# 配置文件路径（关键词/清洗规则配置化 — P2）
KEYWORDS_CONFIG_YAML = os.path.join(_WORKSPACE, "learning", "config", "keywords_config.yaml")
CLEANING_CONFIG_YAML = os.path.join(_WORKSPACE, "learning", "config", "cleaning_config.yaml")

# CI 脚本路径
CI_REGRESSION_SH = os.path.join(_SKILL_SCRIPTS_DIR, "ci_regression.sh")
HISTORY_REPLAY_PY = os.path.join(_SKILL_SCRIPTS_DIR, "history_replay.py")
ACCURACY_COMPARISON_PY = os.path.join(_SKILL_SCRIPTS_DIR, "accuracy_comparison.py")

# 数据库依赖
try:
    from db.connection import get_default_db_config
    import psycopg2
except ImportError:
    get_default_db_config = None
    psycopg2 = None


# ════════════════════════════════════════════════════════════
# 通用工具函数
# ════════════════════════════════════════════════════════════

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


def _make_alias_key(name: str, shipper_id: str) -> str:
    """生成去重 key"""
    return f"{name.strip().lower()}||{shipper_id.strip()}"


def _get_shipper_id_for_correction(entity_name: str) -> Optional[str]:
    """通过 order_feedback 获取 entity_name 对应的 shipper_id (owner_code)"""
    conn = _get_db_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT of_.owner_code
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


# ════════════════════════════════════════════════════════════
# 建议生成函数（5 类）
# ════════════════════════════════════════════════════════════

def generate_alias_suggestions(lookback_days: int = 7, min_count: int = 3) -> List[Dict]:
    """
    SKU 别名建议：从 order_corrections 查高频 sku 纠正。
    Returns: [{"order_name", "system_name", "count", "shipper_id"}]
    """
    conn = _get_db_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT entity_name, corrected_value, COUNT(*) AS cnt
            FROM order_corrections
            WHERE correction_type = 'sku'
              AND created_at >= NOW() - make_interval(days => %s)
            GROUP BY entity_name, corrected_value
            HAVING COUNT(*) >= %s
            ORDER BY cnt DESC
        """, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[improver] alias query failed: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return []

    existing = _load_existing_aliases(SKU_ALIASES_YAML)
    existing_keys = {_make_alias_key(a.get("order_product_name", ""), a.get("shipper_id", "")) for a in existing}

    suggestions = []
    for entity_name, corrected_value, cnt in rows:
        shipper_id = _get_shipper_id_for_correction(entity_name)
        if not shipper_id:
            continue
        key = _make_alias_key(entity_name, shipper_id)
        if key in existing_keys:
            continue
        suggestions.append({
            "order_name": entity_name,
            "system_name": corrected_value,
            "count": cnt,
            "shipper_id": shipper_id,
        })
        existing_keys.add(key)

    return suggestions


def generate_field_alias_suggestions(lookback_days: int = 7, min_count: int = 2) -> List[Dict]:
    """
    字段别名建议：从 unknown_fields_log 查高频未知字段。
    Returns: [{"raw_field", "suggested_standard", "count", "shipper_id"}]
    """
    conn = _get_db_connection()
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
            LIMIT 20
        """, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[improver] field_alias query failed: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return []

    existing = _load_existing_aliases(FIELD_ALIASES_YAML)
    existing_keys = {_make_alias_key(a.get("raw_field_name", ""), a.get("shipper_id", "")) for a in existing}

    suggestions = []
    for field_name, shipper_id, cnt in rows:
        shipper_id = shipper_id or ""
        key = _make_alias_key(field_name, shipper_id)
        if key in existing_keys:
            continue
        suggested = _suggest_standard_field(field_name)
        if suggested == "待人工确认":
            continue  # 无法自动推断的不生成建议
        suggestions.append({
            "raw_field": field_name,
            "suggested_standard": suggested,
            "count": cnt,
            "shipper_id": shipper_id,
        })
        existing_keys.add(key)

    return suggestions


def _suggest_standard_field(raw_field_name: str) -> str:
    """启发式字段名映射"""
    raw_lower = raw_field_name.strip().lower()
    mapping = {
        "store_name": ["门店", "店铺", "店名", "收货点", "配送点"],
        "product_name": ["商品", "产品", "品名", "货品", "物品"],
        "quantity": ["数量", "数目", "个数", "件数"],
        "product_spec": ["规格", "包装", "尺寸"],
        "unit": ["单位", "计量"],
        "address": ["地址", "详细地址", "收货地址"],
        "contact_person": ["联系", "收货人", "收件人"],
        "phone": ["电话", "手机", "联系号码"],
    }
    for std, keywords in mapping.items():
        if any(k in raw_lower for k in keywords):
            return std
    return "待人工确认"


def generate_keyword_suggestions(lookback_days: int = 30, min_count: int = 5) -> List[Dict]:
    """
    关键词词库建议：从 keyword_candidates_log 查高频未匹配关键词。
    Returns: [{"keyword", "count", "sample_names"}]
    """
    conn = _get_db_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT extracted_keywords, COUNT(*) as cnt,
                   ARRAY_AGG(DISTINCT order_product_name) as sample_names
            FROM keyword_candidates_log
            WHERE detected_at >= CURRENT_DATE - INTERVAL '%s days'
              AND extracted_keywords IS NOT NULL AND extracted_keywords != ''
            GROUP BY extracted_keywords
            HAVING COUNT(*) >= %s
            ORDER BY cnt DESC
            LIMIT 20
        """, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[improver] keyword query failed: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return []

    return [{"keyword": r[0], "count": r[1], "sample_names": r[2][:5]} for r in rows]


def generate_cleaning_suggestions(lookback_days: int = 30, min_count: int = 3) -> List[Dict]:
    """
    清洗规则建议：从 cleaning_rule_gap_log 查高频清洗缺口。
    Returns: [{"original_name", "cleaned_name", "count"}]
    """
    conn = _get_db_connection()
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
            LIMIT 20
        """, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[improver] cleaning query failed: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return []

    return [{"original_name": r[0], "cleaned_name": r[1], "count": r[2]} for r in rows]


THRESHOLD_CONFIG_YAML = os.path.join(_WORKSPACE, "learning", "config", "threshold_config.yaml")


def _load_threshold_config() -> Dict:
    """加载阈值配置文件"""
    if not os.path.exists(THRESHOLD_CONFIG_YAML):
        return {}
    try:
        with open(THRESHOLD_CONFIG_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# layer_name → (section, config_key) 映射
_LAYER_TO_CONFIG_KEY = {
    # SKU matcher layers
    "layer1_exact":          ("sku_matcher", "layer1_exact"),
    "layer1b_despec":        ("sku_matcher", "layer1_exact"),
    "layer2_fuzzy":          ("sku_matcher", "layer2_fuzzy_direct"),
    "layer2_5_global":       ("sku_matcher", "layer2_fuzzy_confirm"),
    "layer3_keyword":        ("sku_matcher", "layer3_keyword"),
    "fallback":              ("sku_matcher", "fallback_min"),
    # Store matcher layers
    "layer0_phone":          ("store_matcher", "layer0_phone_min"),
    "layer1_company":        ("store_matcher", "layer1_company"),
    "layer2_store_exact":    ("store_matcher", "layer2_exact"),
    "layer3_store_fuzzy":    ("store_matcher", "layer3_fuzzy"),
    "layer3_5_keyword":      ("store_matcher", "layer3_5_keyword"),
    "layer4_floor":          ("store_matcher", "layer4_floor"),
}


def calculate_optimal_threshold(entity_type: str, layer_name: str,
                                 correction_rate: float, total: int) -> Optional[Dict]:
    """
    基于历史数据计算某层的最优阈值。

    Args:
        entity_type: 'sku' 或 'store'
        layer_name: 匹配层名称
        correction_rate: 纠正率（百分比）
        total: 样本总数

    Returns:
        {"current": float, "suggested": float, "reason": str, "confidence": float}
        或 None（无法计算）
    """
    cfg = _load_threshold_config()
    tuning = cfg.get("tuning", {})
    step_down = tuning.get("step_down", 0.05)
    step_up = tuning.get("step_up", 0.03)
    corr_threshold = tuning.get("correction_rate_threshold", 30)
    success_high = tuning.get("success_rate_high", 95)
    min_sample_increase = tuning.get("min_sample_for_increase", 100)
    min_thresh = tuning.get("min_threshold", 0.3)
    max_thresh = tuning.get("max_threshold", 0.99)

    # 找到当前阈值
    section_key, config_key = _LAYER_TO_CONFIG_KEY.get(layer_name, (None, None))
    if not section_key:
        return None
    section = cfg.get(section_key, {})
    current = section.get(config_key)
    if current is None:
        return None

    # 计算建议值
    if correction_rate > corr_threshold:
        # 纠正率过高 → 降低阈值（让匹配更宽松，减少纠正）
        suggested = max(min_thresh, round(current - step_down, 2))
        if suggested == current:
            return None
        return {
            "current": current,
            "suggested": suggested,
            "reason": f"纠正率 {correction_rate:.1f}% > {corr_threshold}%，降低阈值以放宽匹配",
            "confidence": min(0.9, total / 200.0),
            "direction": "down",
        }
    elif correction_rate < 5 and total >= min_sample_increase:
        # 纠正率很低 + 样本充足 → 可以提高阈值（更严格，减少误匹配）
        success_rate = 100.0 - correction_rate
        if success_rate >= success_high:
            suggested = min(max_thresh, round(current + step_up, 2))
            if suggested == current:
                return None
            return {
                "current": current,
                "suggested": suggested,
                "reason": f"纠正率仅 {correction_rate:.1f}%，样本 {total} 次，可提高阈值减少误匹配",
                "confidence": min(0.85, total / 300.0),
                "direction": "up",
            }
    return None


def generate_threshold_suggestions(lookback_days: int = 30, min_count: int = 10,
                                    rate_threshold: int = 30) -> List[Dict]:
    """
    阈值调优建议（v2 — 区分 SKU/门店，输出具体建议值）。

    查询 order_corrections 按 (correction_type, match_layer) 分组，
    对每层调用 calculate_optimal_threshold() 计算具体建议值。

    Returns:
        [{
            "entity_type": "sku"|"store",
            "layer": str,
            "correction_rate": float,
            "total": int,
            "current_threshold": float,
            "suggested_threshold": float,
            "direction": "down"|"up",
            "reason": str,
            "confidence": float,
            "risk": "low"|"medium"|"high"
        }]
    """
    conn = _get_db_connection()
    if not conn:
        return []

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT correction_type, match_layer,
              COUNT(*) as total,
              SUM(CASE WHEN auto_matched THEN 1 ELSE 0 END) as confirmed,
              SUM(CASE WHEN NOT auto_matched THEN 1 ELSE 0 END) as corrected,
              ROUND((SUM(CASE WHEN NOT auto_matched THEN 1 ELSE 0 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100)::NUMERIC, 2) as correction_rate
            FROM order_corrections
            WHERE created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY correction_type, match_layer
            HAVING COUNT(*) >= %s
            ORDER BY correction_rate DESC
        """, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[improver] threshold query failed: {e}", flush=True)
        try:
            conn.close()
        except Exception:
            pass
        return []

    suggestions = []
    for corr_type, layer, total, confirmed, corrected, corr_rate in rows:
        entity_type = "store" if corr_type in ("store", "store_name") else "sku"
        rate_f = float(corr_rate)

        optimal = calculate_optimal_threshold(entity_type, layer, rate_f, total)
        if optimal:
            risk = "high" if entity_type == "store" and optimal["direction"] == "up" else "medium"
            suggestions.append({
                "entity_type": entity_type,
                "layer": layer,
                "correction_rate": rate_f,
                "total": total,
                "current_threshold": optimal["current"],
                "suggested_threshold": optimal["suggested"],
                "direction": optimal["direction"],
                "reason": optimal["reason"],
                "confidence": optimal["confidence"],
                "risk": risk,
            })
        elif rate_f > rate_threshold:
            # 无法计算具体值，但仍输出文字建议
            suggestions.append({
                "entity_type": entity_type,
                "layer": layer,
                "correction_rate": rate_f,
                "total": total,
                "current_threshold": None,
                "suggested_threshold": None,
                "direction": "down",
                "reason": f"纠正率 {rate_f}% > {rate_threshold}%，建议人工检查 {layer} 层阈值",
                "confidence": 0.5,
                "risk": "medium",
            })

    return suggestions


def apply_threshold_changes(suggestions: List[Dict]) -> int:
    """
    将阈值建议写入 threshold_config.yaml。

    Args:
        suggestions: generate_threshold_suggestions() 返回的建议列表

    Returns:
        成功修改的阈值数量
    """
    cfg = _load_threshold_config()
    if not cfg:
        print("[improver] threshold_config.yaml not found or empty", flush=True)
        return 0

    changed = 0
    for s in suggestions:
        if s.get("suggested_threshold") is None:
            continue
        layer = s["layer"]
        section_key, config_key = _LAYER_TO_CONFIG_KEY.get(layer, (None, None))
        if not section_key or section_key not in cfg:
            continue

        old_val = cfg[section_key].get(config_key)
        new_val = s["suggested_threshold"]
        if old_val == new_val:
            continue

        cfg[section_key][config_key] = new_val
        changed += 1
        print(f"[improver] threshold {section_key}.{config_key}: {old_val} → {new_val}", flush=True)

    if changed == 0:
        return 0

    try:
        with open(THRESHOLD_CONFIG_YAML, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"[improver] Updated {changed} thresholds in {THRESHOLD_CONFIG_YAML}", flush=True)
        return changed
    except Exception as e:
        print(f"[improver] threshold YAML write failed: {e}", flush=True)
        return 0


# ════════════════════════════════════════════════════════════
# 关键词词库 / 清洗规则 apply（P2.1 + P2.2）
# ════════════════════════════════════════════════════════════

def apply_keyword_changes(suggestions: List[Dict]) -> int:
    """
    将高频未匹配关键词写入 keywords_config.yaml。
    格式：
      auto_keywords:
        - keyword: "新词"
          source: self_learning
          added_date: "2026-06-15"
          sample_names: ["商品A", "商品B"]
          occurrence_count: 7
    """
    existing = _load_yaml_config(KEYWORDS_CONFIG_YAML)
    auto_keywords = existing.get("auto_keywords", []) or []
    existing_kw = {k.get("keyword", "").strip().lower() for k in auto_keywords}
    product_types = existing.get("product_types", []) or []
    product_type_keys = {str(k).strip().lower() for k in product_types}

    added = 0
    today_str = datetime.date.today().isoformat()

    for s in suggestions:
        keyword = s.get("keyword", "").strip()
        if not keyword:
            continue
        if keyword.lower() in existing_kw:
            continue
        auto_keywords.append({
            "keyword": keyword,
            "source": "self_learning",
            "added_date": today_str,
            "sample_names": (s.get("sample_names") or [])[:5],
            "occurrence_count": s.get("count", 0),
        })
        if keyword.lower() not in product_type_keys:
            product_types.append(keyword)
            product_type_keys.add(keyword.lower())
        existing_kw.add(keyword.lower())
        added += 1

    if added == 0:
        return 0

    existing["auto_keywords"] = auto_keywords
    existing["product_types"] = product_types
    try:
        os.makedirs(os.path.dirname(KEYWORDS_CONFIG_YAML), exist_ok=True)
        with open(KEYWORDS_CONFIG_YAML, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
        print(f"[improver] Added {added} keywords to {KEYWORDS_CONFIG_YAML}", flush=True)
        return added
    except Exception as e:
        print(f"[improver] keyword config write failed: {e}", flush=True)
        return 0


def apply_cleaning_changes(suggestions: List[Dict]) -> int:
    """
    将清洗规则缺口记录写入 cleaning_config.yaml（供人工 review 后手动改正则）。
    不直接修改 _clean_product_name 的正则（高风险），只记录候选规则。
    格式：
      candidate_rules:
        - original_name: "果糖-"
          cleaned_name: "果糖"
          suggested_pattern: "[-_./\\\\,;:]+$"
          source: self_learning
          added_date: "2026-06-15"
          occurrence_count: 5
          status: pending_review
    """
    existing = _load_yaml_config(CLEANING_CONFIG_YAML)
    candidate_rules = existing.get("candidate_rules", []) or []
    existing_keys = {(r.get("original_name", ""), r.get("cleaned_name", "")) for r in candidate_rules}

    added = 0
    today_str = datetime.date.today().isoformat()

    for s in suggestions:
        original = s.get("original_name", "").strip()
        cleaned = s.get("cleaned_name", "").strip()
        if not original or not cleaned:
            continue
        key = (original, cleaned)
        if key in existing_keys:
            continue
        # 启发式推断正则模式
        suggested_pattern = _infer_cleaning_pattern(original, cleaned)
        candidate_rules.append({
            "original_name": original,
            "cleaned_name": cleaned,
            "suggested_pattern": suggested_pattern,
            "source": "self_learning",
            "added_date": today_str,
            "occurrence_count": s.get("count", 0),
            "status": "pending_review",
        })
        existing_keys.add(key)
        added += 1

    if added == 0:
        return 0

    existing["candidate_rules"] = candidate_rules
    try:
        os.makedirs(os.path.dirname(CLEANING_CONFIG_YAML), exist_ok=True)
        with open(CLEANING_CONFIG_YAML, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
        print(f"[improver] Added {added} cleaning rule candidates to {CLEANING_CONFIG_YAML}", flush=True)
        return added
    except Exception as e:
        print(f"[improver] cleaning config write failed: {e}", flush=True)
        return 0


def _load_yaml_config(yaml_path: str) -> Dict:
    """加载 yaml 配置，不存在返回空 dict"""
    if not os.path.exists(yaml_path):
        return {}
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _infer_cleaning_pattern(original: str, cleaned: str) -> str:
    """
    启发式推断清洗规则正则。
    比较 original 和 cleaned 的差异，推测需要去除的字符模式。
    """
    if original == cleaned:
        return ""
    # 检查末尾差异
    if cleaned == original.rstrip("-_./\\,;: "):
        return r"[-_./\\,;: ]+$"
    # 检查开头差异
    if cleaned == original.lstrip("-_./\\,;: "):
        return r"^[-_./\\,;: ]+"
    # 检查中间替换
    if len(cleaned) < len(original):
        # 找被替换/删除的部分
        for i, (a, b) in enumerate(zip(original, cleaned)):
            if a != b:
                return f"字符 '{a}' 在位置 {i} 被替换或删除"
    return "需人工分析"

def run_ci_validation() -> Dict:
    """
    跑 CI 回归测试。
    Returns: {"passed": bool, "stdout": str, "stderr": str, "return_code": int}
    """
    if not os.path.exists(CI_REGRESSION_SH):
        return {"passed": True, "skipped": True, "reason": "CI script not found"}

    try:
        result = subprocess.run(
            ["bash", CI_REGRESSION_SH],
            capture_output=True, text=True, timeout=300,
            cwd=_WORKSPACE
        )
        return {
            "passed": result.returncode == 0,
            "stdout": result.stdout[-2000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
            "return_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "error": "CI timeout (300s)", "return_code": -1}
    except Exception as e:
        return {"passed": False, "error": str(e), "return_code": -1}


def run_history_replay() -> Dict:
    """
    跑历史订单回放。
    Returns: {"success": bool, "report_path": str, "summary": str, ...}
    """
    if not os.path.exists(HISTORY_REPLAY_PY):
        return {"success": True, "skipped": True, "reason": "replay script not found"}

    try:
        result = subprocess.run(
            ["python3", HISTORY_REPLAY_PY, "--json-output"],
            capture_output=True, text=True, timeout=600,
            cwd=_WORKSPACE
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return {"success": True, **data}
            except json.JSONDecodeError:
                return {"success": True, "output": result.stdout[-2000:]}
        else:
            return {"success": False, "stderr": result.stderr[-1000:]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "history replay timeout (600s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_accuracy_comparison() -> Dict:
    """
    准确率对比。
    Returns: {"success": bool, "old_accuracy": float, "new_accuracy": float, "delta": float, ...}
    """
    if not os.path.exists(ACCURACY_COMPARISON_PY):
        return {"success": True, "skipped": True, "reason": "comparison script not found"}

    try:
        result = subprocess.run(
            ["python3", ACCURACY_COMPARISON_PY, "--json-output"],
            capture_output=True, text=True, timeout=600,
            cwd=_WORKSPACE
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                return {"success": True, **data}
            except json.JSONDecodeError:
                return {"success": True, "output": result.stdout[-2000:]}
        else:
            return {"success": False, "stderr": result.stderr[-1000:]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "accuracy comparison timeout (600s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════════════════════
# 应用建议（写入 yaml）
# ════════════════════════════════════════════════════════════

def apply_suggestions(suggestions: List[Dict], yaml_path: str = None) -> int:
    """写入 SKU 别名到 sku_aliases_auto.yaml"""
    yaml_path = yaml_path or SKU_ALIASES_YAML
    os.makedirs(os.path.dirname(yaml_path), exist_ok=True)

    existing = _load_existing_aliases(yaml_path)
    existing_keys = {_make_alias_key(a.get("order_product_name", ""), a.get("shipper_id", "")) for a in existing}

    today = datetime.date.today().isoformat()
    added = 0
    for s in suggestions:
        key = _make_alias_key(s["order_name"], s["shipper_id"])
        if key in existing_keys:
            continue
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
        return 0

    try:
        data = {"aliases": existing}
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"[improver] Added {added} SKU aliases to {yaml_path}", flush=True)
        return added
    except Exception as e:
        print(f"[improver] YAML write failed: {e}", flush=True)
        return 0


def apply_field_alias_suggestions(suggestions: List[Dict]) -> int:
    """写入字段别名到 field_aliases_auto.yaml"""
    os.makedirs(os.path.dirname(FIELD_ALIASES_YAML), exist_ok=True)

    existing = _load_existing_aliases(FIELD_ALIASES_YAML)
    existing_keys = {_make_alias_key(a.get("raw_field_name", ""), a.get("shipper_id", "")) for a in existing}

    today = datetime.date.today().isoformat()
    added = 0
    for s in suggestions:
        key = _make_alias_key(s["raw_field"], s["shipper_id"])
        if key in existing_keys:
            continue
        existing.append({
            "raw_field_name": s["raw_field"],
            "standard_field": s["suggested_standard"],
            "shipper_id": s["shipper_id"],
            "source": "auto",
            "confirm_count": s["count"],
            "confirmed_at": today,
        })
        existing_keys.add(key)
        added += 1

    if added == 0:
        return 0

    try:
        data = {"aliases": existing}
        with open(FIELD_ALIASES_YAML, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"[improver] Added {added} field aliases to {FIELD_ALIASES_YAML}", flush=True)
        return added
    except Exception as e:
        print(f"[improver] Field alias YAML write failed: {e}", flush=True)
        return 0


# ════════════════════════════════════════════════════════════
# 通知（完整版：建议 + CI + 准确率）
# ════════════════════════════════════════════════════════════

def _build_full_report(all_suggestions: Dict, ci_result: Dict,
                       replay_result: Dict, accuracy_result: Dict) -> str:
    """构建完整报告（建议内容 + CI 验证 + 准确率对比）"""
    today = datetime.date.today().isoformat()
    lines = [f"# 📋 自学习改进建议报告（{today}）\n"]

    # 1. 建议汇总
    total = sum(len(v) for v in all_suggestions.values())
    lines.append(f"## 建议总数：{total} 条\n")

    # SKU 别名
    sku_suggestions = all_suggestions.get("sku_alias", [])
    if sku_suggestions:
        lines.append("### SKU 别名候选\n")
        lines.append("| 订单商品名 | 系统商品名 | 纠正次数 |")
        lines.append("|-----------|-----------|---------|")
        for s in sku_suggestions:
            lines.append(f"| {s['order_name']} | {s['system_name']} | {s['count']} |")
        lines.append("")

    # 字段别名
    field_suggestions = all_suggestions.get("field_alias", [])
    if field_suggestions:
        lines.append("### 字段别名候选\n")
        lines.append("| 未知字段名 | 建议标准字段 | 出现次数 | 货主 |")
        lines.append("|-----------|-------------|---------|------|")
        for s in field_suggestions:
            lines.append(f"| {s['raw_field']} | {s['suggested_standard']} | {s['count']} | {s['shipper_id'] or '通用'} |")
        lines.append("")

    # 阈值调优
    threshold_suggestions = all_suggestions.get("threshold", [])
    if threshold_suggestions:
        lines.append("### 阈值调优建议\n")
        lines.append("| 类型 | 匹配层 | 纠正率% | 样本数 | 当前阈值 | 建议阈值 | 方向 | 置信度 | 风险 |")
        lines.append("|------|--------|---------|--------|---------|---------|------|--------|------|")
        for s in threshold_suggestions:
            cur_t = s.get('current_threshold')
            sug_t = s.get('suggested_threshold')
            cur_str = f"{cur_t}" if cur_t is not None else "-"
            sug_str = f"**{sug_t}**" if sug_t is not None else "人工检查"
            direction_icon = "⬇️" if s.get('direction') == 'down' else "⬆️"
            conf = f"{s.get('confidence', 0):.0%}"
            lines.append(f"| {s['entity_type']} | {s['layer']} | {s['correction_rate']} | {s['total']} | {cur_str} | {sug_str} | {direction_icon} | {conf} | {s['risk']} |")
        lines.append("")
        for s in threshold_suggestions:
            if s.get('reason'):
                lines.append(f"- **{s['layer']}**：{s['reason']}")
        lines.append("\n*阈值变更前需先跑 CI 回归 + 历史订单回放验证*")
        lines.append("")

    # 关键词
    keyword_suggestions = all_suggestions.get("keyword", [])
    if keyword_suggestions:
        lines.append("### 关键词词库候选\n")
        lines.append("| 关键词 | 出现次数 | 示例 |")
        lines.append("|-------|---------|------|")
        for s in keyword_suggestions:
            samples = ", ".join(s.get("sample_names", [])[:3])
            lines.append(f"| {s['keyword']} | {s['count']} | {samples} |")
        lines.append("")

    # 清洗规则
    cleaning_suggestions = all_suggestions.get("cleaning", [])
    if cleaning_suggestions:
        lines.append("### 清洗规则候选\n")
        lines.append("| 原始名 | 清洗后 | 次数 |")
        lines.append("|--------|--------|------|")
        for s in cleaning_suggestions:
            lines.append(f"| {s['original_name']} | {s['cleaned_name']} | {s['count']} |")
        lines.append("")

    # 2. CI 验证结果
    lines.append("---\n")
    lines.append("## CI 验证结果\n")
    if ci_result.get("skipped"):
        lines.append(f"*跳过：{ci_result.get('reason', 'unknown')}*\n")
    elif ci_result.get("passed"):
        lines.append("✅ **CI 回归测试全部通过**\n")
        if ci_result.get("stdout"):
            # 取最后几行摘要
            last_lines = ci_result["stdout"].strip().split("\n")[-5:]
            lines.append("```\n" + "\n".join(last_lines) + "\n```\n")
    else:
        lines.append("❌ **CI 回归测试未通过**\n")
        lines.append(f"```\n{ci_result.get('stderr', ci_result.get('error', 'unknown'))}\n```\n")

    # 3. 历史回放结果
    lines.append("## 历史订单回放\n")
    if replay_result.get("skipped"):
        lines.append(f"*跳过：{replay_result.get('reason', 'unknown')}*\n")
    elif replay_result.get("success"):
        lines.append("✅ **历史订单回放完成**\n")
        if replay_result.get("summary"):
            lines.append(f"> {replay_result['summary']}\n")
    else:
        lines.append(f"⚠️ 回放失败：{replay_result.get('error', replay_result.get('stderr', 'unknown'))}\n")

    # 4. 准确率对比
    lines.append("## 准确率对比\n")
    if accuracy_result.get("skipped"):
        lines.append(f"*跳过：{accuracy_result.get('reason', 'unknown')}*\n")
    elif accuracy_result.get("success"):
        lines.append("✅ **准确率对比完成**\n")
        if accuracy_result.get("old_accuracy") is not None:
            old = accuracy_result.get("old_accuracy", 0)
            new = accuracy_result.get("new_accuracy", 0)
            delta = accuracy_result.get("delta", 0)
            icon = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
            lines.append(f"- 旧版准确率: {old}%")
            lines.append(f"- 新版准确率: {new}%")
            lines.append(f"- 变化: {icon} {delta:+.1f}%")
        if accuracy_result.get("output"):
            lines.append(f"\n```\n{accuracy_result['output'][:500]}\n```\n")
    else:
        lines.append(f"⚠️ 对比失败：{accuracy_result.get('error', accuracy_result.get('stderr', 'unknown'))}\n")

    # 5. 操作指引
    lines.append("---\n")
    lines.append("**操作指引**：")
    lines.append("- 回复「确认添加」→ 执行低风险建议（yaml 别名）")
    lines.append("- 回复「跳过」→ 忽略本次")
    lines.append("- 回复「修改」→ 人工调整后重新验证")

    return "\n".join(lines)


def _notify_full_report(report: str) -> bool:
    """推送完整报告"""
    try:
        scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from notification_sender import send_notification
        return send_notification("improvement_report", report)
    except ImportError as e:
        print(f"[improver] notification_sender import failed: {e}", flush=True)
        print(f"[improver] Report content (first 500 chars):\n{report[:500]}", flush=True)
        return False
    except Exception as e:
        print(f"[improver] Notification failed: {e}", flush=True)
        return False


def _notify_ci_failure(ci_result: Dict, suggestions_summary: str) -> bool:
    """CI 失败时发送告警"""
    msg = f"❌ CI 验证失败，改进建议未推送\n\nCI 输出：\n{ci_result.get('stderr', ci_result.get('error', ''))[:500]}\n\n待处理建议数：{suggestions_summary}"
    try:
        scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from notification_sender import send_notification
        return send_notification("ci_failure", msg)
    except Exception:
        return False


# ════════════════════════════════════════════════════════════
# 迭代决策集成（P3.1 — 从 skill_operation_monitor 迁入）
# ════════════════════════════════════════════════════════════

def run_iteration_decision(report_data: Dict) -> Dict:
    """
    运行迭代决策引擎（从 skill_operation_monitor/decider.py 迁入核心逻辑）。
    
    Args:
        report_data: 包含 match_rate, low_confidence_rate, intervention_rate 等指标
    
    Returns:
        {"decision": str, "priority": str, "reasons": list, "recommendations": list}
    """
    thresholds = {
        "match_rate_warning": 0.85,
        "match_rate_critical": 0.70,
        "low_conf_rate_warning": 0.10,
        "user_intervention_warning": 0.15,
        "user_intervention_critical": 0.30,
    }

    reasons = []
    recommendations = []
    severity = "low"

    match_rate = report_data.get("match_rate", 1.0)
    if match_rate < thresholds["match_rate_critical"]:
        reasons.append(f"匹配率 {match_rate:.1%} < {thresholds['match_rate_critical']:.1%}")
        recommendations.append("立即优化 SKU 匹配算法")
        severity = "critical"
    elif match_rate < thresholds["match_rate_warning"]:
        reasons.append(f"匹配率 {match_rate:.1%} < {thresholds['match_rate_warning']:.1%}")
        recommendations.append("计划优化 SKU 匹配算法")
        severity = max(severity, "medium", key=lambda x: ["low", "medium", "high", "critical"].index(x))

    intervention_rate = report_data.get("intervention_rate", 0.0)
    if intervention_rate > thresholds["user_intervention_critical"]:
        reasons.append(f"用户干预率 {intervention_rate:.1%} > {thresholds['user_intervention_critical']:.1%}")
        recommendations.append("立即优化用户体验")
        severity = max(severity, "high", key=lambda x: ["low", "medium", "high", "critical"].index(x))
    elif intervention_rate > thresholds["user_intervention_warning"]:
        reasons.append(f"用户干预率 {intervention_rate:.1%} > {thresholds['user_intervention_warning']:.1%}")
        recommendations.append("优化操作流程")
        severity = max(severity, "medium", key=lambda x: ["low", "medium", "high", "critical"].index(x))

    if severity == "critical":
        decision = "🔴 立即升级"
    elif severity == "high":
        decision = "🟡 计划升级"
    elif severity == "medium":
        decision = "🟡 计划升级（中期）"
    else:
        decision = "🟢 持续监控"
        if not reasons:
            reasons.append("各项指标正常")

    return {
        "decision": decision,
        "priority": severity,
        "reasons": reasons,
        "recommendations": recommendations,
    }


# ════════════════════════════════════════════════════════════
# 主入口：完整改进循环（v2.0）
# ════════════════════════════════════════════════════════════

def run_improvement_cycle(auto_apply: bool = False) -> Dict:
    """
    主入口：执行完整改进循环（v2.0 — 含 CI 验证 + 5 类建议 + 迭代决策）

    流程：
    1. 生成 5 类建议
    2. CI 验证（建议前必须先跑）
    3. 历史回放 + 准确率对比
    4. 迭代决策
    5. 构建完整报告
    6. 推送审批
    7. 自动应用（仅低风险 yaml 变更）

    Args:
        auto_apply: True=直接写入 yaml；False=仅通知，等人工确认

    Returns:
        {
            "suggestions_count": int,
            "by_type": {sku: n, field: n, threshold: n, keyword: n, cleaning: n},
            "ci_passed": bool | None,
            "replay_success": bool | None,
            "accuracy_impact": dict | None,
            "decision": str,
            "applied": int,
            "notified": bool
        }
    """
    print("[improver] Starting improvement cycle v3.3...", flush=True)

    result = {
        "suggestions_count": 0,
        "by_type": {},
        "ci_passed": None,
        "replay_success": None,
        "accuracy_impact": None,
        "decision": "",
        "applied": 0,
        "notified": False,
        "effect_evaluations": 0,
    }
    effect_report = ""

    # Step 0: 效果追踪 — 评估上一次变更的效果（v3.3 闭环补齐）
    print("[improver] Step 0: Evaluating previous changes...", flush=True)
    try:
        from learning.effect_tracker import ensure_schema, evaluate_all_pending, generate_effect_report
        ensure_schema()
        _evaluations = evaluate_all_pending()
        if _evaluations:
            effect_report = generate_effect_report(_evaluations)
            result["effect_evaluations"] = len(_evaluations)
            print(f"[improver] Evaluated {len(_evaluations)} previous changes", flush=True)
        else:
            print("[improver] No pending evaluations", flush=True)
    except Exception as _e:
        print(f"[improver] Step 0 skipped: {_e}", flush=True)

    # Step 1: 生成 5 类建议
    print("[improver] Step 1: Generating suggestions...", flush=True)
    all_suggestions = {
        "sku_alias": generate_alias_suggestions(),
        "field_alias": generate_field_alias_suggestions(),
        "threshold": generate_threshold_suggestions(),
        "keyword": generate_keyword_suggestions(),
        "cleaning": generate_cleaning_suggestions(),
    }
    total = sum(len(v) for v in all_suggestions.values())
    by_type = {k: len(v) for k, v in all_suggestions.items()}

    result.update({
        "suggestions_count": total,
        "by_type": by_type,
    })

    if total == 0:
        print("[improver] 暂无改进建议", flush=True)
        # 即使没建议也跑一次迭代决策
        decision = run_iteration_decision({"match_rate": 1.0, "intervention_rate": 0.0})
        result["decision"] = decision["decision"]
        return result

    print(f"[improver] Found {total} suggestions: {by_type}", flush=True)

    # Step 2: CI 验证（金姐要求：建议前必须先验证）
    print("[improver] Step 2: Running CI validation...", flush=True)
    ci_result = run_ci_validation()
    result["ci_passed"] = ci_result.get("passed")

    if not ci_result.get("passed") and not ci_result.get("skipped"):
        print("[improver] ❌ CI failed, not pushing suggestions", flush=True)
        _notify_ci_failure(ci_result, f"{total} 条待处理")
        return result

    # Step 3: 历史回放 + 准确率对比
    print("[improver] Step 3: Running history replay + accuracy comparison...", flush=True)
    replay_result = run_history_replay()
    accuracy_result = run_accuracy_comparison()
    result["replay_success"] = replay_result.get("success")
    result["accuracy_impact"] = accuracy_result

    # Step 4: 迭代决策
    print("[improver] Step 4: Running iteration decision...", flush=True)
    # 从准确率结果构建决策输入
    decision_input = {
        "match_rate": accuracy_result.get("new_accuracy", 100) / 100.0 if accuracy_result.get("success") else 1.0,
        "intervention_rate": 0.0,  # 后续从 order_feedback 统计
    }
    decision = run_iteration_decision(decision_input)
    result["decision"] = decision["decision"]

    # Step 5: 构建完整报告
    print("[improver] Step 5: Building full report...", flush=True)
    full_report = _build_full_report(all_suggestions, ci_result, replay_result, accuracy_result)
    if effect_report:
        full_report += f"\n\n---\n\n{effect_report}"

    # 附加迭代决策到报告
    full_report += f"\n\n---\n\n## 迭代决策\n\n"
    full_report += f"**决策**: {decision['decision']}\n\n"
    for reason in decision.get("reasons", []):
        full_report += f"- {reason}\n"

    # Step 6: 推送审批
    print("[improver] Step 6: Sending notification...", flush=True)
    notified = _notify_full_report(full_report)
    result["notified"] = notified

    # Step 7: 自动应用（仅低风险 yaml 变更）
    if auto_apply and ci_result.get("passed", ci_result.get("skipped", False)):
        print("[improver] Step 7: Auto-applying low-risk changes...", flush=True)
        applied = 0

        # SKU 别名（低风险）
        if all_suggestions["sku_alias"]:
            applied += apply_suggestions(all_suggestions["sku_alias"])

        # 字段别名（低风险）
        if all_suggestions["field_alias"]:
            applied += apply_field_alias_suggestions(all_suggestions["field_alias"])

        # 阈值调优（中风险 — 仅当 CI 通过且有具体建议值时才自动应用）
        threshold_with_values = [s for s in all_suggestions.get("threshold", [])
                                  if s.get("suggested_threshold") is not None]
        if threshold_with_values and ci_result.get("passed"):
            threshold_applied = apply_threshold_changes(threshold_with_values)
            applied += threshold_applied
            if threshold_applied:
                print(f"[improver] Applied {threshold_applied} threshold changes", flush=True)

        # 关键词词库（低风险 — 写入 yaml 配置，不改正则）
        if all_suggestions["keyword"]:
            keyword_applied = apply_keyword_changes(all_suggestions["keyword"])
            applied += keyword_applied
            if keyword_applied:
                print(f"[improver] Added {keyword_applied} keywords to config", flush=True)

        # 清洗规则候选（低风险 — 只记录候选，不改正则，等人工 review）
        if all_suggestions["cleaning"]:
            cleaning_applied = apply_cleaning_changes(all_suggestions["cleaning"])
            applied += cleaning_applied
            if cleaning_applied:
                print(f"[improver] Added {cleaning_applied} cleaning rule candidates", flush=True)

        result["applied"] = applied
        print(f"[improver] Auto-applied {applied} entries", flush=True)
    else:
        if not ci_result.get("passed", ci_result.get("skipped", False)):
            print("[improver] Step 7 skipped: CI not passed", flush=True)
        else:
            print("[improver] Step 7: Waiting for manual confirmation", flush=True)

    # Step 8: 记录本次变更（供下次追踪）— v3.3 闭环补齐
    if result.get("applied", 0) > 0:
        print("[improver] Step 8: Recording changes for tracking...", flush=True)
        try:
            from learning.effect_tracker import record_batch_changes
            for change_type, items in all_suggestions.items():
                if not items:
                    continue
                tracker_type = "cleaning_rule" if change_type == "cleaning" else change_type
                if tracker_type in ("sku_alias", "field_alias", "keyword", "cleaning_rule"):
                    record_batch_changes(tracker_type, items)
            # 阈值单独记录
            threshold_applied = [s for s in all_suggestions.get("threshold", [])
                                 if s.get("suggested_threshold") is not None]
            if threshold_applied:
                record_batch_changes("threshold", threshold_applied)
            print("[improver] Step 8 complete", flush=True)
        except Exception as _e:
            print(f"[improver] Step 8 skipped: {_e}", flush=True)

    print(f"[improver] Cycle complete: {result}", flush=True)
    return result


# ════════════════════════════════════════════════════════════
# CLI 入口
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="自学习改进执行器 v2.0")
    parser.add_argument("--auto-apply", action="store_true", help="直接写入 yaml，不等人工确认")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--min-count", type=int, default=3)
    parser.add_argument("--skip-ci", action="store_true", help="跳过 CI 验证（仅用于调试）")
    args = parser.parse_args()

    result = run_improvement_cycle(auto_apply=args.auto_apply)
    print(f"\n结果: {json.dumps(result, ensure_ascii=False, indent=2)}")

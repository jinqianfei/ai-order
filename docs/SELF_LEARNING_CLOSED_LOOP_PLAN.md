# 自学习闭环系统 — 完整实施方案

> **作者**：AI建单助手
> **日期**：2026-06-14
> **状态**：差距分析完成，待金姐确认后实施
> **关联文档**：`SELF_LEARNING_MODULE_PLAN.md`（原方案）、`MEMORY.md`（版本记录）

---

## 0. 一句话总结

**现状**：方案设计了"收集→分析→建议→验证→实施"五层闭环，但实际代码只完成了 60%，且 3 套监控系统各自独立，建议生成前不跑 CI 验证。

**目标**：补齐缺失环节，打通完整闭环 —— **收集 → 分析 → 生成建议 → CI 验证 → 人工审批 → 实施 → 效果追踪**。

---

## 1. 当前代码全景（6 个位置的代码）

| # | 位置 | 职责 | 数据源 | 状态 |
|---|------|------|--------|------|
| 1 | `learning/` | 自学习主模块：collector + adapter + improver + 分析脚本 | DB 3 张表 | 核心存在，缺 3 个分析项 |
| 2 | `skills/.../learn/` | shim 软链接 → 指向 `learning/` | - | 仅转发 |
| 3 | `skills/.../scripts/` | CI 回归 + history_replay + accuracy_comparison | DB + 文件 | 独立运行，未被集成 |
| 4 | `skills/skill_operation_monitor/` | 运营监控 v1：reporter + decider | JSONL 文件 | 独立系统，未打通 |
| 5 | `skills/skill_ops_monitor/` | 运营监控 v2：alert + metrics + 飞书卡片 | DB 另一套表 | 独立系统，未打通 |
| 6 | `skills/skill_skill_monitor/` | Skill 版本 git 变更监控 | Git | 独立系统 |

**核心问题**：3 套监控系统数据源不同、分析维度不同、互不通信。

---

## 2. 方案 vs 代码 — 逐项差距

### 2.1 六项分析能力

| # | 分析项 | 方案设计 | 代码现状 | 差距 |
|---|--------|---------|---------|------|
| 1 | SKU 别名候选 | 高频纠正 → yaml | ✅ L1采集 ✅ L2分析 ✅ L3写入 ✅ 加载 | ✅ 已完成 |
| 2 | **字段别名候选** | 未知字段 → yaml | ❌ 采集断（parser 检测了 unknown_fields 但没 emit）<br>❌ 分析缺（无 analyze_field_alias_candidates）<br>❌ 写入缺（improver 只有路径常量，无逻辑）<br>✅ 加载侧已完成（_merge_auto_aliases） | ❌ **3 环全断** |
| 3 | 层成功率统计 | 各层成功率 | ✅ 采集 ✅ 分析 | ✅ 已完成 |
| 4 | 阈值调优建议 | 纠正率排名 | ✅ 采集 ✅ 分析<br>❌ 无自动执行器（只输出建议文字） | ⚠️ 分析有，无执行 |
| 5 | **关键词词库更新** | 新品词 → 建议加词 | ❌ 无事件 ❌ 无分析 ❌ 无执行<br>（product_types/flavor_types 硬编码在 _sku_mapper.py） | ❌ **3 层全缺** |
| 6 | **清洗规则增强** | 新边界字符 → 建议正则 | ❌ 无事件 ❌ 无分析 ❌ 无执行<br>（_clean_product_name 正则硬编码） | ❌ **3 层全缺** |

### 2.2 CI-before-建议（金姐明确要求）

**方案原文**（第 4.4 节）：
> 调优流程：分析脚本输出建议值 → **跑历史订单回放** → **对比准确率** → 金姐确认 → 改代码

**实际代码**（`improver.py.run_improvement_cycle()`）：
```
generate_alias_suggestions() → notify_suggestions() → [等人工确认] → apply_suggestions()
```

| 缺失环节 | 影响 |
|----------|------|
| ❌ 没调用 `history_replay.py` | 建议前不验证历史订单 |
| ❌ 没调用 `accuracy_comparison.py` | 不知道建议会不会降低准确率 |
| ❌ 没调用 `ci_regression.sh` | 建议可能引入回归 |
| ❌ `daily_wrap.sh` Step 2.5 也没集成 | 每日自动流程跳过验证 |

### 2.3 人工决策监控

| 已有 | 缺失 |
|------|------|
| ✅ collector 采集纠正记录 | ❌ 无"哪些层被纠正最多"排名 |
| ✅ layer_success_rate 表 | ❌ 无"纠正趋势"（增加还是减少） |
| ✅ decider.py 迭代决策 | ❌ SKU 匹配 vs 门店匹配 分类统计 |
| ✅ alert_detector 异常检测 | ❌ 三套系统不互通 |

### 2.4 字段别名 yaml

| 环节 | 状态 | 代码位置 |
|------|------|---------|
| ✅ yaml 文件 | 存在（空） | `field_mapping/rules/field_aliases_auto.yaml` |
| ✅ 加载逻辑 | 已实现 | `_field_transformer.py:_merge_auto_aliases()` |
| ✅ improver 常量 | 已定义 | `improver.py:41: FIELD_ALIASES_YAML = ...` |
| ❌ 采集层 | parser 检测了 unknown_fields 但没 emit | `core/parser.py:543-566` |
| ❌ 分析函数 | 不存在 | analyze_data.py 无此函数 |
| ❌ 写入逻辑 | improver 只写 SKU 别名 | `improver.py:apply_suggestions()` |

---

## 3. 完整闭环架构（目标状态）

```
┌─────────────────────────────────────────────────────────────────────┐
│                     自学习闭环系统（目标状态）                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   │
│  │ ① 收集  │ → │ ② 分析  │ → │ ③ 建议  │ → │ ④ 验证  │ → │ ⑤ 审批  │   │
│  │EventBus│   │analyze │   │improver│   │CI+回放 │   │人工确认│   │
│  │collector│  │_data.py│   │        │   │对比    │   │飞书交互│   │
│  └────────┘   └────────┘   └────────┘   └────────┘   └────────┘   │
│       ↓             ↓            ↓            ↓            ↓        │
│  10个事件      6项分析能力    改进方案      准确率验证     确认/拒绝  │
│  → 3张DB表     → 分析报告     → yaml变更    → CI 全过      → 执行/回滚│
│                 → 趋势洞察     → 代码变更    → 对比报告              │
│                                                                       │
│  ┌────────┐                                                          │
│  │ ⑥ 追踪  │ ← 实施后持续监控                                        │
│  │monitor │                                                          │
│  └────────┘                                                          │
│       ↓                                                              │
│  效果确认（纠正率是否下降/准确率是否提升）                              │
│                                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                      统一监控面板（合并 3 套系统）                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ 数据源统一：DB 3张表 + JSONL 日志 + Git 变更                    │    │
│  │ 分析维度统一：匹配率 / 纠正率 / 层成功率 / 处理量 / 版本变更      │    │
│  │ 输出统一：一份日报 + 一份迭代建议（不重复推送）                   │    │
│  └──────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. 要做的事（按优先级排列）

### 🔴 P1 — 闭环核心（不补这些，闭环不成立）

#### P1.1 字段别名候选 — 补齐 3 环

**① 采集层**（改 `core/parser.py`）
- 在 `unknown_fields` 检测后新增 `EventBus.emit("unknown_field_detected", {...})`
- 事件 payload：`{field_name, shipper_id, order_context, timestamp}`

**② 采集器**（改 `learning/collector.py`）
- 新增 `on_unknown_field_detected` handler
- 写入新表 `unknown_fields_log`（或复用 order_corrections，correction_type='field'）

**③ 分析函数**（改 `learning/scripts/analyze_data.py`）
- 新增 `analyze_field_alias_candidates()`
- 逻辑：滚动 7 天，同一 (raw_field_name, shipper_id) ≥ 2 次 → 候选

**④ 改进执行器**（改 `learning/improver.py`）
- 新增 `generate_field_alias_suggestions()`
- 新增 `apply_field_alias_suggestions()` → 写入 `field_aliases_auto.yaml`
- 格式：`{raw_field_name, standard_field, shipper_id, source, confirm_count}`

**⑤ 配置**（改 `learning/config/analysis_config.yaml`）
- 新增 `field_alias_candidates` section

#### P1.2 CI-before-建议集成

**改 `learning/improver.py` 的 `run_improvement_cycle()`**：

```python
def run_improvement_cycle(auto_apply=False):
    # 1. 生成建议
    suggestions = generate_alias_suggestions()
    
    if not suggestions:
        return result
    
    # 2. 【新增】CI 验证（建议前先跑）
    ci_result = run_ci_validation(suggestions)
    if not ci_result["passed"]:
        # CI 不过，不推送建议，报警
        notify_ci_failure(ci_result)
        return result
    
    # 3. 【新增】历史订单回放
    replay_result = run_history_replay(suggestions)
    
    # 4. 【新增】准确率对比
    accuracy_result = run_accuracy_comparison(replay_result)
    
    # 5. 生成完整报告（建议 + CI结果 + 准确率对比）
    full_report = build_full_report(suggestions, ci_result, accuracy_result)
    
    # 6. 推送审批
    notified = notify_suggestions(full_report)
    
    # 7. 人工确认后执行
    ...
```

**新增辅助函数**：
- `run_ci_validation(suggestions)` → 调用 `ci_regression.sh`，返回 pass/fail + 详细结果
- `run_history_replay(suggestions)` → 调用 `history_replay.py`，返回匹配率
- `run_accuracy_comparison(replay_result)` → 调用 `accuracy_comparison.py`，返回对比数据
- `build_full_report(...)` → 合并所有数据，生成一份完整报告

**同步改 `ops/daily_wrap.sh` Step 2.5**：
- 调用 `run_improvement_cycle()` 时自动触发 CI 验证

#### P1.3 人工决策监控 — 分类排名 + 趋势

**新增分析函数**（改 `learning/scripts/analyze_data.py`）：

```python
def analyze_correction_ranking():
    """纠正类型 × 匹配层 排名分析"""
    # 输出：哪个层被纠正最多、哪种纠正类型最频繁
    
def analyze_correction_trend():
    """纠正趋势分析（周环比）"""
    # 输出：某种纠正是在增加还是减少
    
def analyze_sku_vs_store_correction():
    """SKU匹配 vs 门店匹配 分类统计"""
    # 输出：SKU 层 vs 门店层 的纠正率对比
```

**新增报告 section**（改 `generate_report()`）：
- Section 4：纠正排名
- Section 5：纠正趋势
- Section 6：SKU vs 门店分类

---

### 🟡 P2 — 增强能力（让闭环更智能）

#### P2.1 关键词词库更新

**① 采集层**
- 在 `_sku_mapper.py` 的 unmatched_items 产生时 emit `unmatched_sku_keyword` 事件
- payload：`{order_name, extracted_keywords, shipper_id}`

**② 采集器**
- 新增 `on_unmatched_sku_keyword` handler
- 写入 `order_corrections`（correction_type='keyword'）

**③ 分析函数**
- 新增 `analyze_keyword_candidates()`
- 逻辑：滚动 30 天，某词在未匹配商品中反复出现 ≥ 5 次 → 候选新关键词

**④ 改进执行器**
- 生成建议 → CI 验证 → 人工审批 → 修改 `_sku_mapper.py` 的 `product_types` / `flavor_types` 列表

#### P2.2 清洗规则增强

**① 采集层**
- 在 `_clean_product_name` 处理前后对比，如果清洗后名称变化很大且最终 unmatched，emit `cleaning_rule_gap` 事件
- payload：`{original_name, cleaned_name, unmatched, shipper_id}`

**② 采集器**
- 新增 `on_cleaning_rule_gap` handler

**③ 分析函数**
- 新增 `analyze_cleaning_rule_candidates()`
- 逻辑：滚动 30 天，某类字符模式反复导致未匹配 → 候选新清洗规则

**④ 改进执行器**
- 生成正则建议 → CI 验证 → 人工审批 → 修改 `_clean_product_name` 正则

#### P2.3 阈值调优自动执行

当前 `analyze_threshold_tuning()` 只输出建议文字，没有执行器。

**新增**（改 `learning/improver.py`）：
- `generate_threshold_suggestions()` → 基于纠正率计算建议阈值
- CI 验证：用建议阈值跑 history_replay，对比准确率
- 人工审批 → 修改 `_sku_mapper.py` 的阈值常量

---

### 🟢 P3 — 系统整合（减少重复，统一输出）

#### P3.1 三套监控系统整合

**现状问题**：
- `learning/` 自学习 → DB 3 张表 → `/tmp/analysis_report_*.md`
- `skill_operation_monitor/` → JSONL 文件 → Markdown + 飞书
- `skill_ops_monitor/` → DB 另一套表 → 飞书卡片

**整合方案**：

| 保留 | 整合 | 废弃 |
|------|------|------|
| `learning/` 自学习核心 | 作为分析引擎 | - |
| `skill_ops_monitor/` 告警 + 飞书卡片 | 作为通知渠道 | - |
| - | `skill_operation_monitor/` 的 decider 逻辑迁入 `learning/improver.py` | `skill_operation_monitor/` 的 reporter（被 ops_monitor 替代） |
| - | JSONL 日志迁入 DB（统一数据源） | JSONL 文件存储 |

**统一日报流程**：
```
每天 10:00 daily_wrap.sh
  → Step 1: 断档检测
  → Step 2: DB 数据汇总
  → Step 2.5: 自学习分析 + CI 验证 + 改进建议
  → Step 2.6: decider 迭代决策（从 skill_operation_monitor 迁入）
  → Step 3: 统一飞书推送（一份报告，不重复）
```

#### P3.2 方案文档修正

- `SELF_LEARNING_MODULE_PLAN.md` 第 116-120 行：3 个分析项标记从"✅"改为"❌ 未实现"
- Phase 3 checklist：字段别名候选、关键词、清洗规则标记为"[ ] 未完成"
- 版本号对齐

---

## 5. 完整闭环流程图

```
用户提交订单
    ↓
┌─────────────── ① 收集 ───────────────┐
│  EventBus 10 个事件                    │
│  → collector.py 写入 3 张 DB 表        │
│  → unknown_fields 事件（新增）          │
│  → unmatched_keyword 事件（新增）       │
│  → cleaning_rule_gap 事件（新增）       │
└───────────────────────────────────────┘
    ↓
┌─────────────── ② 分析 ───────────────┐
│  analyze_data.py 6 项分析              │
│  ├─ SKU 别名候选（✅ 已有）            │
│  ├─ 字段别名候选（❌ 新增）            │
│  ├─ 层成功率统计（✅ 已有）            │
│  ├─ 阈值调优建议（⚠️ 补执行器）       │
│  ├─ 关键词词库更新（❌ 新增）          │
│  └─ 清洗规则增强（❌ 新增）            │
│  + 纠正排名（❌ 新增）                 │
│  + 纠正趋势（❌ 新增）                 │
│  + SKU vs 门店分类（❌ 新增）          │
└───────────────────────────────────────┘
    ↓
┌─────────────── ③ 生成建议 ───────────┐
│  improver.py                          │
│  ├─ generate_alias_suggestions()      │
│  ├─ generate_field_alias_suggestions()│  ← 新增
│  ├─ generate_threshold_suggestions()  │  ← 新增
│  ├─ generate_keyword_suggestions()    │  ← 新增
│  └─ generate_cleaning_suggestions()   │  ← 新增
└───────────────────────────────────────┘
    ↓
┌─────────────── ④ CI 验证 ────────────┐  ← 金姐要求，必须加
│  建议生成后、推送前自动执行：           │
│  ├─ ci_regression.sh（53+ 测试全过？）│
│  ├─ history_replay.py（历史订单回放） │
│  └─ accuracy_comparison.py（准确率对比）│
│                                        │
│  结果：                                │
│  ├─ CI 不过 → 不推送，报警             │
│  ├─ 准确率下降 → 标记风险，附报告推送  │
│  └─ 全部通过 → 正常推送               │
└───────────────────────────────────────┘
    ↓
┌─────────────── ⑤ 人工审批 ───────────┐
│  飞书推送完整报告：                     │
│  ├─ 建议内容                           │
│  ├─ CI 验证结果                        │
│  ├─ 准确率对比数据                     │
│  └─ 影响范围评估                       │
│                                        │
│  金姐回复：                            │
│  ├─ "确认" → 执行                     │
│  ├─ "跳过" → 记录，下次再看           │
│  └─ "修改" → 人工调整后重新验证       │
└───────────────────────────────────────┘
    ↓
┌─────────────── ⑥ 实施 ──────────────┐
│  低风险（yaml 变更）：                  │
│  ├─ 写入 sku_aliases_auto.yaml        │
│  ├─ 写入 field_aliases_auto.yaml      │
│  └─ 下次订单自动生效                   │
│                                        │
│  中高风险（代码变更）：                 │
│  ├─ 新分支 → CI → 金姐确认 → merge    │
│  └─ 阈值/关键词/清洗规则/新匹配层     │
└───────────────────────────────────────┘
    ↓
┌─────────────── ⑦ 效果追踪 ──────────┐
│  实施后持续监控：                       │
│  ├─ 纠正率是否下降                     │
│  ├─ 匹配率是否提升                     │
│  ├─ 层成功率是否改善                   │
│  └─ 下个周期的分析报告自动对比         │
└───────────────────────────────────────┘
    ↓
  回到 ①（闭环飞轮）
```

---

## 6. 实施计划（建议顺序）

| 阶段 | 任务 | 预估工时 | 依赖 |
|------|------|---------|------|
| **Sprint 1** | P1.2 CI-before-建议集成 | 2h | 无 |
| **Sprint 1** | P1.1 字段别名候选 3 环补齐 | 2h | 无 |
| **Sprint 1** | P1.3 纠正排名 + 趋势分析 | 1h | 无 |
| **Sprint 2** | P2.1 关键词词库更新 3 层 | 2h | Sprint 1 |
| **Sprint 2** | P2.2 清洗规则增强 3 层 | 2h | Sprint 1 |
| **Sprint 2** | P2.3 阈值调优自动执行 | 1h | Sprint 1 |
| **Sprint 3** | P3.1 三套监控整合 | 3h | Sprint 1+2 |
| **Sprint 3** | P3.2 方案文档修正 | 0.5h | Sprint 1+2 |
| **总计** | | **~13.5h** | |

### Sprint 1 详细说明

#### Task 1.1：字段别名候选（3 环补齐）

**改 `core/parser.py`**：
```python
# 在 unknown_fields 检测后新增
if unknown_fields:
    try:
        from events.bus import EventBus
        EventBus.emit("unknown_field_detected", {
            "field_names": unknown_fields,
            "shipper_id": shipper_id or "",
            "order_context": raw_data,
            "timestamp": time.time()
        })
    except Exception:
        pass
```

**改 `learning/collector.py`**：
```python
# 新增 handler
def on_unknown_field_detected(self, data: Dict):
    """记录未知字段"""
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        for field_name in data.get("field_names", []):
            cur.execute("""
                INSERT INTO unknown_fields_log 
                (field_name, shipper_id, detected_at)
                VALUES (%s, %s, NOW())
            """, (field_name, data.get("shipper_id", "")))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[collector] unknown_field write failed: {e}")
    finally:
        conn.close()
```

**改 `learning/scripts/analyze_data.py`**：
```python
def analyze_field_alias_candidates():
    """字段别名候选（滚动 7 天，同一字段 ≥ 2 次）"""
    cfg = _analysis_cfg.get("field_alias_candidates", {})
    lookback_days = cfg.get("lookback_days", 7)
    min_count = cfg.get("min_detection_count", 2)
    
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
        """, (lookback_days, min_count))
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        return []
    finally:
        conn.close()
```

**改 `learning/improver.py`**：
```python
def generate_field_alias_suggestions(lookback_days=7, min_count=2):
    """从 unknown_fields_log 生成字段别名建议"""
    # 类似 generate_alias_suggestions()，但数据源是 unknown_fields_log
    # 输出格式：{raw_field_name, suggested_standard, shipper_id, count}
    ...

def apply_field_alias_suggestions(suggestions):
    """写入 field_aliases_auto.yaml"""
    # 类似 apply_suggestions()，但写入 FIELD_ALIASES_YAML
    ...
```

**新增 DB 表**：
```sql
CREATE TABLE IF NOT EXISTS unknown_fields_log (
    id SERIAL PRIMARY KEY,
    field_name TEXT NOT NULL,
    shipper_id TEXT,
    detected_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_unknown_fields_name ON unknown_fields_log(field_name);
CREATE INDEX idx_unknown_fields_time ON unknown_fields_log(detected_at DESC);
```

**改 `learning/config/analysis_config.yaml`**：
```yaml
field_alias_candidates:
  lookback_days: 7
  min_detection_count: 2
  max_results: 20
```

#### Task 1.2：CI-before-建议集成

**改 `learning/improver.py`**：
```python
import subprocess

def run_ci_validation(context: str = "pre_suggestion") -> Dict:
    """跑 CI 回归测试"""
    ci_script = os.path.join(_WORKSPACE, "skills", "skill_order_to_huading_template", 
                             "scripts", "ci_regression.sh")
    try:
        result = subprocess.run(
            ["bash", ci_script],
            capture_output=True, text=True, timeout=300,
            cwd=_WORKSPACE
        )
        passed = result.returncode == 0
        return {
            "passed": passed,
            "stdout": result.stdout[-2000:],  # 截取最后 2000 字符
            "stderr": result.stderr[-1000:],
            "return_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "error": "CI timeout (300s)"}
    except Exception as e:
        return {"passed": False, "error": str(e)}

def run_history_replay_validation() -> Dict:
    """跑历史订单回放"""
    replay_script = os.path.join(_WORKSPACE, "skills", "skill_order_to_huading_template",
                                 "scripts", "history_replay.py")
    try:
        result = subprocess.run(
            ["python3", replay_script, "--json-output"],
            capture_output=True, text=True, timeout=600,
            cwd=_WORKSPACE
        )
        return json.loads(result.stdout) if result.returncode == 0 else {"error": result.stderr}
    except Exception as e:
        return {"error": str(e)}

def run_accuracy_comparison() -> Dict:
    """准确率对比"""
    # 调用 accuracy_comparison.py
    ...
```

**改 `run_improvement_cycle()`**：
```python
def run_improvement_cycle(auto_apply=False):
    """主入口：执行完整改进循环（含 CI 验证）"""
    print("[improver] Starting improvement cycle...", flush=True)

    # Step 1: 生成建议
    suggestions = generate_alias_suggestions()
    field_suggestions = generate_field_alias_suggestions()  # 新增
    all_suggestions = {
        "sku_alias": suggestions,
        "field_alias": field_suggestions,
    }
    
    total = sum(len(v) for v in all_suggestions.values())
    result = {"suggestions_count": total, "applied": 0, "notified": False, 
              "ci_passed": None, "accuracy_impact": None}
    
    if total == 0:
        print("[improver] 暂无改进建议", flush=True)
        return result
    
    # Step 2: CI 验证（金姐要求：建议前必须先验证）
    print("[improver] Running CI validation...", flush=True)
    ci_result = run_ci_validation("pre_suggestion")
    result["ci_passed"] = ci_result["passed"]
    
    if not ci_result["passed"]:
        print("[improver] CI failed, not pushing suggestions", flush=True)
        _notify_ci_failure(ci_result, all_suggestions)
        return result
    
    # Step 3: 历史回放 + 准确率对比
    print("[improver] Running history replay...", flush=True)
    replay_result = run_history_replay_validation()
    accuracy_result = run_accuracy_comparison()
    result["accuracy_impact"] = accuracy_result
    
    # Step 4: 生成完整报告
    full_report = _build_full_report(all_suggestions, ci_result, replay_result, accuracy_result)
    
    # Step 5: 推送审批
    notified = _notify_full_report(full_report)
    result["notified"] = notified
    
    # Step 6: 人工确认后执行（auto_apply 仅用于低风险 yaml 变更）
    if auto_apply and ci_result["passed"]:
        applied = 0
        if suggestions:
            applied += apply_suggestions(suggestions)
        if field_suggestions:
            applied += apply_field_alias_suggestions(field_suggestions)
        result["applied"] = applied
    
    return result
```

#### Task 1.3：纠正排名 + 趋势分析

**改 `learning/scripts/analyze_data.py`**：

```python
def analyze_correction_ranking():
    """纠正类型 × 匹配层 排名"""
    conn = get_db_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT correction_type, match_layer, COUNT(*) as cnt
            FROM order_corrections
            WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY correction_type, match_layer
            ORDER BY cnt DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        return []
    finally:
        conn.close()

def analyze_correction_trend():
    """纠正趋势（本周 vs 上周）"""
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
                COALESCE(t.cnt, 0) - COALESCE(l.cnt, 0) as delta
            FROM this_week t
            FULL OUTER JOIN last_week l ON t.correction_type = l.correction_type
            ORDER BY ABS(COALESCE(t.cnt, 0) - COALESCE(l.cnt, 0)) DESC
        """)
        rows = cur.fetchall()
        cur.close()
        return rows
    except Exception as e:
        return []
    finally:
        conn.close()

def analyze_sku_vs_store():
    """SKU 匹配 vs 门店匹配 分类统计"""
    conn = get_db_connection()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                entity_type,
                COUNT(*) as total,
                SUM(success_count) as successes,
                SUM(user_corrected_count) as corrections,
                ROUND(AVG(success_rate) * 100, 2) as avg_success_pct
            FROM layer_success_rate
            GROUP BY entity_type
        """)
        rows = cur.fetchall()
        cur.close()
        return {r[0]: {"total": r[1], "successes": r[2], "corrections": r[3], "avg_rate": r[4]} 
                for r in rows}
    except Exception as e:
        return {}
    finally:
        conn.close()
```

**改 `generate_report()`**：新增 Section 4/5/6

---

## 7. 需要金姐决定的事项

| # | 决策点 | 选项 | 建议 |
|---|--------|------|------|
| 1 | 字段别名候选的存储方式 | A) 新建 `unknown_fields_log` 表<br>B) 复用 `order_corrections` 表（correction_type='field'） | B（减少表数） |
| 2 | CI 验证失败时的行为 | A) 完全不推送建议<br>B) 推送但标记"CI 未通过"<br>C) 推送给管理员而非金姐 | A（CI 不过说明当前代码有问题，建议没有意义） |
| 3 | 三套监控是否整合 | A) 整合到 learning/ 统一<br>B) 保持独立但统一日报<br>C) 暂时不动 | B（最小改动） |
| 4 | 关键词/清洗规则的实施方式 | A) 代码变更（改 .py）<br>B) 配置文件化（改 .yaml） | B（更安全，但需要改 _sku_mapper.py 加载逻辑） |
| 5 | Sprint 优先级 | A) 先做 P1（闭环核心）<br>B) P1+P2 一起做 | A（先确保闭环成立） |

---

## 8. 文件变更清单

| 文件 | 操作 | 所属 Sprint |
|------|------|-------------|
| `core/parser.py` | 改 — 新增 unknown_fields emit | S1 |
| `learning/collector.py` | 改 — 新增 3 个 handler | S1 |
| `learning/scripts/analyze_data.py` | 改 — 新增 5 个分析函数 | S1+S2 |
| `learning/improver.py` | 改 — CI 集成 + 字段别名 + 完整报告 | S1 |
| `learning/config/analysis_config.yaml` | 改 — 新增配置项 | S1 |
| `learning/schema.sql` | 改 — 新增表/字段 | S1 |
| `ops/daily_wrap.sh` | 改 — Step 2.5 集成 CI 验证 | S1 |
| `_sku_mapper.py` | 改 — unmatched emit（S2）+ 关键词配置化（S2） | S2 |
| `_clean_product_name` | 改 — gap emit（S2）+ 正则配置化（S2） | S2 |
| `learning/feedback_parser.py` | 改 — 解析字段修改类型 | S1 |
| `SELF_LEARNING_MODULE_PLAN.md` | 改 — 修正标记 | S3 |
| `docs/SELF_LEARNING_CLOSED_LOOP_PLAN.md` | 新建 — 本文档 | S1 |

---

*AI建单助手 | 2026-06-14 01:35 GMT+8*

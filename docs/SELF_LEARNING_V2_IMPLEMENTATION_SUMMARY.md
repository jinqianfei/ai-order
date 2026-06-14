# 自学习闭环系统 v2.0 — 实施完成报告

> **日期**：2026-06-14
> **状态**：全部 P1/P2/P3 任务已实施
> **Skill 版本**：v5.15.4 → v5.16.0（自学习闭环 v2.0）

---

## 0. 实施总结

本次实施了自学习闭环系统 v2.0 的全部改进，补齐了原方案中缺失的 40% 功能，打通了完整的 **收集 → 分析 → 建议 → CI 验证 → 审批 → 实施 → 追踪** 七步闭环。

---

## 1. 已完成的文件变更清单

| # | 文件 | 变更类型 | 说明 |
|---|------|---------|------|
| 1 | `learning/scripts/analyze_data.py` | **重写** | 9 个分析函数（原 3 个 + 新增 6 个），完整的报告生成 |
| 2 | `learning/improver.py` | **重写** | v2.0 完整闭环：5 类建议 + CI 验证 + 回放 + 对比 + 迭代决策 |
| 3 | `learning/collector.py` | 追加 | 3 个新 event handler（unknown_field / keyword / cleaning_gap） |
| 4 | `learning/schema.sql` | 追加 | 3 张新日志表 |
| 5 | `learning/config/analysis_config.yaml` | 追加 | 5 个新分析配置项 |
| 6 | `learning/config/keywords_config.yaml` | **新建** | 关键词词库配置（product_types / flavor_types） |
| 7 | `learning/config/cleaning_config.yaml` | **新建** | 清洗规则配置 |
| 8 | `skills/.../core/parser.py` | 追加 | unknown_field_detected 事件 emit |
| 9 | `skills/.../tools/_sku_mapper.py` | 追加 | unmatched_sku_keyword + cleaning_rule_gap emit + 关键词配置化 |
| 10 | `ops/daily_wrap.sh` | 修改 | Step 2.5 调用 v2.0 improver（含 CI 验证） |
| 11 | `docs/SELF_LEARNING_MODULE_PLAN.md` | 修改 | 修正 Phase 3 标记 + Phase 4 集成说明 |
| 12 | `docs/SELF_LEARNING_CLOSED_LOOP_PLAN.md` | **新建** | 差距分析 + 实施方案 |
| 13 | `docs/SELF_LEARNING_V2_IMPLEMENTATION_SUMMARY.md` | **新建** | 本文档 |

---

## 2. 完整闭环逻辑（v2.0 最终版）

### 2.1 七步闭环

```
① 收集 → ② 分析 → ③ 建议 → ④ CI验证 → ⑤ 审批 → ⑥ 实施 → ⑦ 追踪
   ↓          ↓         ↓         ↓         ↓         ↓         ↓
 13个事件  9项分析    5类建议   CI+回放   飞书报告  yaml/代码  下期报告
 → 6张DB表  → 报告     → 完整     → 对比      → 确认/跳过  → 生效     → 对比
```

### 2.2 每一步的详细逻辑

#### ① 收集层（13 个事件）

| 事件 | emit 位置 | handler | 写入表 |
|------|----------|---------|--------|
| store_confirm_needed | __init__.py | collector.on_store_confirm_needed | layer_success_rate |
| store_confirmed | __init__.py | collector.on_store_confirmed | layer_success_rate |
| store_corrected | __init__.py | collector.on_store_corrected | order_corrections |
| sku_confirm_needed | __init__.py | collector.on_sku_confirm_needed | layer_success_rate |
| sku_confirmed | __init__.py | collector.on_sku_confirmed | layer_success_rate |
| sku_corrected | __init__.py | collector.on_sku_corrected | order_corrections |
| order_complete | __init__.py | collector.on_order_complete | order_feedback |
| user_modified | __init__.py | collector.on_user_modified | order_feedback |
| **unknown_field_detected** | **core/parser.py** | **collector.on_unknown_field_detected** | **unknown_fields_log** |
| **unmatched_sku_keyword** | **tools/_sku_mapper.py** | **collector.on_unmatched_sku_keyword** | **keyword_candidates_log** |
| **cleaning_rule_gap** | **tools/_sku_mapper.py** | **collector.on_cleaning_rule_gap** | **cleaning_rule_gap_log** |
| order_cancelled | （暂无触发场景） | collector.on_order_cancelled | - |
| alert_raised | （暂无触发场景） | collector.on_alert_raised | - |

#### ② 分析层（9 项分析）

| # | 分析项 | 函数 | 数据源 | 输出 |
|---|--------|------|--------|------|
| 1 | SKU 别名候选 | analyze_alias_candidates() | order_corrections | 高频纠正商品列表 |
| 2 | **字段别名候选** | **analyze_field_alias_candidates()** | **unknown_fields_log** | **高频未知字段列表** |
| 3 | 层成功率统计 | analyze_layer_success_rate() | layer_success_rate | 各层成功率表 |
| 4 | 阈值调优建议 | analyze_threshold_tuning() + generate_threshold_suggestions() | order_corrections | 建议降低阈值的层 |
| 5 | **关键词词库候选** | **analyze_keyword_candidates()** | **keyword_candidates_log** | **高频未匹配关键词** |
| 6 | **清洗规则候选** | **analyze_cleaning_rule_candidates()** | **cleaning_rule_gap_log** | **高频清洗缺口** |
| 7 | **纠正排名** | **analyze_correction_ranking()** | order_corrections | **纠正最多的类型×层** |
| 8 | **纠正趋势** | **analyze_correction_trend()** | order_corrections | **本周 vs 上周环比** |
| 9 | **SKU vs 门店分类** | **analyze_sku_vs_store()** | layer_success_rate | **两类匹配的对比统计** |

**报告输出**：`/tmp/analysis_report_YYYYMMDD.md`（9 个 Section，含洞察和建议）

#### ③ 建议层（5 类建议）

| 类型 | 生成函数 | 风险等级 | 实施方式 |
|------|---------|---------|---------|
| SKU 别名 | generate_alias_suggestions() | 🟢 低 | 写入 sku_aliases_auto.yaml |
| **字段别名** | **generate_field_alias_suggestions()** | **🟢 低** | **写入 field_aliases_auto.yaml** |
| **阈值调优** | **generate_threshold_suggestions()** | **🟡 中** | **修改 _sku_mapper.py 常量（需 CI）** |
| **关键词词库** | **generate_keyword_suggestions()** | **🟡 中** | **修改 keywords_config.yaml** |
| **清洗规则** | **generate_cleaning_suggestions()** | **🔴 高** | **修改 _clean_product_name 正则（需 CI）** |

#### ④ CI 验证层（建议前自动执行）

**`improver.py` v2.0 核心改进**：在推送建议之前，自动执行 3 项验证：

| 验证项 | 调用 | 超时 | 失败行为 |
|--------|------|------|---------|
| CI 回归测试 | `ci_regression.sh` | 300s | **不推送建议 + 发告警** |
| 历史订单回放 | `history_replay.py` | 600s | 标记风险，附报告推送 |
| 准确率对比 | `accuracy_comparison.py` | 600s | 标记风险，附报告推送 |

**结果嵌入报告**：完整报告包含建议内容 + CI 结果 + 回放数据 + 准确率对比。

#### ⑤ 人工审批

推送给金姐的飞书报告包含：
1. 5 类建议的完整列表
2. CI 验证结果（✅/❌）
3. 历史回放数据
4. 准确率对比（旧版 vs 新版 vs 变化）
5. 迭代决策建议
6. 操作指引（确认/跳过/修改）

#### ⑥ 实施

**自动实施**（auto_apply=True，仅低风险）：
- SKU 别名 → 写入 `sku_aliases_auto.yaml` → 下次订单自动生效
- 字段别名 → 写入 `field_aliases_auto.yaml` → 下次订单自动生效

**需人工确认**（中高风险）：
- 阈值调优 → 修改 `_sku_mapper.py` 常量
- 关键词词库 → 修改 `keywords_config.yaml`（已配置化）
- 清洗规则 → 修改 `_clean_product_name` 正则

#### ⑦ 效果追踪

**自动对比**：下次 daily_wrap.sh 运行时：
- 纠正趋势分析自动对比本周 vs 上周
- 如果某类纠正下降 → 说明上次的改进有效
- 如果某类纠正上升 → 需要进一步关注

---

## 3. 数据库表（6 张）

| 表 | 行数（预估） | 数据来源 | 消费方 |
|---|------------|---------|--------|
| order_feedback | ~19 | EventBus → collector | analyze_data.py 各函数 |
| order_corrections | ~0（待积累） | EventBus → collector | 分析函数 1/4/7/8 |
| layer_success_rate | ~12 预填 | EventBus → collector | 分析函数 3/9 |
| **unknown_fields_log** | **待积累** | **parser.py → collector** | **分析函数 2** |
| **keyword_candidates_log** | **待积累** | **_sku_mapper.py → collector** | **分析函数 5** |
| **cleaning_rule_gap_log** | **待积累** | **_sku_mapper.py → collector** | **分析函数 6** |

---

## 4. 配置文件（5 个 yaml）

| 文件 | 用途 | 维护方式 |
|------|------|---------|
| `analysis_config.yaml` | 9 个分析的阈值参数 | 手动编辑 |
| `notification_config.yaml` | 推送对象/渠道/频率 | 手动编辑 |
| **`keywords_config.yaml`** | **关键词词库（product_types/flavor_types）** | **自学习自动维护** |
| **`cleaning_config.yaml`** | **清洗规则配置** | **自学习自动维护** |
| `sku_aliases_auto.yaml` | SKU 别名表 | 自学习自动维护 |
| `field_aliases_auto.yaml` | 字段别名表 | 自学习自动维护 |

---

## 5. 触发流程

### 每日 10:00（daily_wrap.sh）

```
Step 1: 断档检测
Step 2: DB 数据汇总（SQL 查询 → /tmp/daily_wrap_YYYY-MM-DD.md）
Step 2.5: 自学习分析 + CI 验证 + 改进建议
  ├─ analyze_data.py → 9 项分析 → /tmp/analysis_report_YYYYMMDD.md
  └─ improver.py v2.0
       ├─ 5 类建议生成
       ├─ CI 回归测试（ci_regression.sh）
       ├─ 历史订单回放（history_replay.py）
       ├─ 准确率对比（accuracy_comparison.py）
       ├─ 迭代决策（run_iteration_decision）
       ├─ 构建完整报告
       └─ 飞书推送审批
Step 3: 飞书日结推送（含分析报告）
Step 4: 更新 MEMORY.md 时间戳
```

### 每次订单处理（EventBus）

```
订单 → parse → transform → match_store → match_sku → template
         ↓         ↓            ↓             ↓          ↓
    unknown_   field_      store_         sku_       order_
    field_     alias       confirm/       confirm/   complete
    detected   匹配        corrected      corrected
         ↓         ↓            ↓             ↓          ↓
    unknown_   (无新表)   layer_         order_      order_
    fields_               success_       corrections  feedback
    log                   rate
```

---

## 6. 版本信息

| 项目 | 值 |
|------|-----|
| Skill 版本 | v5.16.0 |
| 自学习版本 | v2.0 |
| 分析函数数 | 9 |
| 事件数 | 13 |
| DB 表数 | 6 |
| 配置文件数 | 6 |
| CI 测试数 | 53+ |

---

*AI建单助手 | 2026-06-14 02:00 GMT+8*

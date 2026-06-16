# 工作区全量代码 Review 报告

> **审查时间**：2026-06-16 11:15 GMT+8
> **审查范围**：skills/ + learning/ + memory/ + memory_system/ + events/ + ops/ + launchd/
> **审查人**：AI建单助手

---

## 一、Skill 方案（skill_order_to_huading_template v5.16.3）

### 1.1 架构（分层设计）

```
__init__.py (~850行) ← 主编排层，唯一公开接口 execute()
    ├── core/              ← 核心逻辑层（4模块）
    │   ├── parser.py       (593行) — LLM订单解析
    │   ├── store_matcher.py(511行) — 门店匹配（6层）
    │   ├── sku_matcher.py  (366行) — SKU映射（6层）
    │   └── generator.py    (427行) — 华鼎31字段模板生成
    ├── tools/             ← 底层算法实现（5文件，3551行）
    │   ├── _order_parser.py    (1015行)
    │   ├── _field_transformer.py(410行)
    │   ├── _store_matcher.py   (686行)
    │   ├── _sku_mapper.py      (1200行) ← 最核心文件
    │   └── _template_generator.py(225行)
    ├── db/                ← 数据库层（6文件，1086行）
    ├── config/            ← 配置层（yaml 3文件）
    ├── field_mapping/     ← 字段映射规则（5个货主yaml）
    ├── events/            ← 事件总线 shim（→ 工作区级）
    └── scripts/           ← CI/测试脚本（12个）
```

### 1.2 核心流程

```
execute(order_input)
  → Step 1: tools_parse()      — LLM提取订单JSON（支持Excel/图片/PDF/文字）
  → Step 2: tools_transform()  — 规则库标准化字段
  → Step 3: _match_store()     — 门店匹配（6层）⚠️ 必须用户确认
  → Step 4: _match_sku()       — SKU映射（6层，按货主过滤）⚠️ 用户确认
  → Step 5: _generate_multi_store_template() — 生成31字段Excel
```

### 1.3 SKU匹配6层算法

| 层级 | 策略 | 置信度 |
|------|------|--------|
| Layer 0 | 别名表精确匹配（product_name_alias） | 0.98 |
| Layer 1 | 精确匹配（sku_name / customer_code） | 0.95 |
| Layer 1b | 去规格后精确匹配 | 0.93 |
| Layer 2 | 模糊匹配+规格校验（≥0.8直接返回） | 0.85 cap |
| Layer 2.5 | 全量相似度+关键词加成 | 0.85 cap |
| Layer 3 | 分词关键词匹配+包含关系加成 | 0.88 cap |

**单位匹配加成**（v5.14.0新增）：`_compute_match_score()` 统一打分，order_unit 匹配 +0.20，spec 匹配 +0.10

### 1.4 门店匹配6层

| 层级 | 策略 |
|------|------|
| Layer 0 | 手机号/收货人/地址辅助匹配 |
| Layer 1 | 客户公司精确匹配 owner_name |
| Layer 2 | 门店名称精确匹配 |
| Layer 3 | 门店名称模糊匹配（相似度） |
| Layer 3.5 | 关键词交叉匹配（兜底） |
| Layer 3.6 | 联系人姓名兜底 |

### 1.5 实现状态

| 项目 | 状态 | 备注 |
|------|------|------|
| 多格式输入（Excel/图片/PDF/文字） | ✅ 完成 | LLM + OCR |
| 门店6层匹配 | ✅ 完成 | 3327条门店数据 |
| SKU 6层匹配 | ✅ 完成 | 1832条SKU，12货主 |
| 多门店订单支持 | ✅ 完成 | confirmed_store 隔离 |
| 31字段华鼎模板生成 | ✅ 完成 | 含默认值填充 |
| 用户确认流程 | ✅ 完成 | 门店+SKU 两步确认 |
| CI 回归测试（53用例） | ✅ 完成 | 100%通过率 |
| 阈值配置化 | ✅ 完成 | threshold_config.yaml |
| 单位匹配加成 | ✅ 完成 | v5.14.0 |
| LLM 解析缓存 | ✅ 完成 | v5.16.3，8倍提速 |
| 端到端测试 | ✅ 完成 | 单门店+多门店均通过 |

---

## 二、自学习模块（learning/ v1.0.0）

### 2.1 架构

```
learning/ (独立于Skill，工作区级)
├── __init__.py         (32行) — auto_init() 入口
├── collector.py        (486行) — 事件订阅 + 数据库写入（13事件）
├── adapter.py          (67行) — 事件payload → DB record 转换
├── feedback_parser.py  (154行) — 解析用户自然语言反馈
├── modifier.py         (88行) — 应用修改到映射结果
├── improver.py         (1317行) — 改进执行器（核心）
├── effect_tracker.py   (575行) — 效果追踪（前后指标对比）
├── llm/                — LLM路由（4 provider: openclaw/openai/openai_compat/custom_http）
├── config/             — 4个yaml配置
│   ├── threshold_config.yaml    — 匹配阈值（可自动调优）
│   ├── keywords_config.yaml     — 关键词词库（可自动更新）
│   ├── cleaning_config.yaml     — 清洗规则候选
│   └── analysis_config.yaml     — 分析阈值
└── scripts/
    ├── analyze_data.py     (695行) — 6+3项数据分析
    ├── daily_summary.py    (133行) — 每日摘要推送
    └── notification_sender.py(177行) — 飞书通知
```

### 2.2 数据库表（7表 + 2视图）

| 表名 | 作用 | 自学习中的数据角色 |
|------|------|-------------------|
| `order_feedback` | 订单反馈主表 | 效果评估数据源 |
| `order_corrections` | 结构化纠正记录 | SKU别名/阈值建议来源 |
| `layer_success_rate` | 匹配层成功率 | 阈值调优依据 |
| `unknown_fields_log` | 未知字段日志 | 字段别名候选来源 |
| `keyword_candidates_log` | 未匹配关键词日志 | 关键词词库候选 |
| `cleaning_rule_gap_log` | 清洗规则缺口 | 清洗规则候选 |
| `applied_changes` | 已实施变更 | 效果追踪 |

### 2.3 完整闭环流程

```
订单处理 → EventBus emit 事件 → FeedbackCollector 写入DB
    ↓
每日 10:05 (launchd) → daily_summary.py → 分析数据
    ↓
手动/定期 → improver.py.run_improvement_cycle()
    ├── Step 0: 效果追踪（评估上次变更）
    ├── Step 1: 生成5类建议（SKU别名/字段别名/阈值/关键词/清洗规则）
    ├── Step 2: CI 验证（ci_regression.sh）
    ├── Step 3: 历史回放 + 准确率对比
    ├── Step 4: 迭代决策引擎
    ├── Step 5: 构建完整报告
    ├── Step 6: 推送飞书审批
    └── Step 7: auto_apply → 写入yaml配置
    ↓
下次 cycle → effect_tracker 评估效果 → 闭环
```

### 2.4 5类改进建议

| 类型 | 数据来源 | 输出目标 | 风险等级 | 自动应用条件 |
|------|----------|----------|----------|-------------|
| SKU别名 | order_corrections (≥3次) | sku_aliases_auto.yaml | 低 | CI通过 |
| 字段别名 | unknown_fields_log (≥2次) | field_aliases_auto.yaml | 低 | CI通过 |
| 阈值调优 | layer_success_rate + corrections | threshold_config.yaml | 中 | CI通过+有具体值 |
| 关键词词库 | keyword_candidates_log (≥5次) | keywords_config.yaml | 低 | CI通过 |
| 清洗规则候选 | cleaning_rule_gap_log (≥3次) | cleaning_config.yaml | 低 | 仅记录，等人工review |

### 2.5 自动化定时任务

| 任务 | 时间 | plist | 功能 |
|------|------|-------|------|
| daily-wrap | 10:00 | com.ai-order.daily-wrap | 总结昨天数据 + 飞书推送 |
| daily-alias-summary | 10:05 | com.ai-order.daily-alias-summary | 别名分析 |
| phase3-maintenance | — | com.ai-order.phase3-maintenance | 记忆维护 |

### 2.6 实现状态

| 项目 | 状态 | 备注 |
|------|------|------|
| EventBus（13事件） | ✅ 完成 | 进程内同步，容错 |
| FeedbackCollector（13事件订阅） | ✅ 完成 | 单例模式，DB容错 |
| EventAdapter | ✅ 完成 | |
| 用户反馈解析（NLP） | ✅ 完成 | 正则提取修改指令 |
| 映射结果修改器 | ✅ 完成 | |
| 5类建议生成 | ✅ 完成 | improver.py |
| CI 验证集成 | ✅ 完成 | 建议前必须先跑 |
| 历史回放 + 准确率对比 | ✅ 完成 | |
| 迭代决策引擎 | ✅ 完成 | 4级严重度 |
| 飞书通知推送 | ✅ 完成 | |
| 自动应用（低风险yaml） | ✅ 完成 | auto_apply 参数控制 |
| 效果追踪（前后对比） | ✅ 完成 | 7天窗口评估 |
| LLM Router（4 provider） | ✅ 完成 | 带回退链 |
| 阈值配置化 | ✅ 完成 | 代码无硬编码 |
| 关键词配置化 | ✅ 完成 | auto_keywords 合并进匹配器 |
| **实际运行数据** | ⚠️ 不足 | 需积累数据验证闭环 |

---

## 三、记忆模块（memory/ + memory_system/）

### 3.1 5层架构

```
┌─────────────────────────────────────────────────┐
│  L5  决策层：MEMORY.md（人工可读，7天摘要）        │ ← 手账，靠L4兜底
├─────────────────────────────────────────────────┤
│  L4 真相源：git log + 代码 + 文件mtime            │ ← 唯一可信任
├─────────────────────────────────────────────────┤
│  L3 索引层：.memory_index/ + Supermemory云        │ ← 语义检索
├─────────────────────────────────────────────────┤
│  L2 协议层：SESSION_START/END/PENDING 协议        │ ← 流程约束
├─────────────────────────────────────────────────┤
│  L1 触发层：version_check + 每日10:00日结         │ ← 自动化守护
└─────────────────────────────────────────────────┘
```

### 3.2 核心组件

| 组件 | 路径 | 行数 | 功能 |
|------|------|------|------|
| MEMORY.md | 根目录 | ~300行 | 人工可读摘要 + 版本记录 |
| 会话日志 | memory/YYYY-MM-DD.md | 6个文件 | 6-1~6-12 |
| 项目记忆 | memory/projects/ai-order/ | PROJECT.md + INDEX.md × 5 | 按维度组织 |
| 凭证索引 | memory/credentials/INDEX.md | | 只记位置，不写明文 |
| 启动协议 | SESSION_START_PROTOCOL.md | | 按需读取触发条件表 |
| 结束协议 | SESSION_END_PROTOCOL.md | | 7步流程 |
| extract_memory.py | memory_system/scripts/ | 262行 | 自动提取记忆 |
| check_quality.py | memory_system/scripts/ | 230行 | 质量检查 |
| reindex.py | memory_system/scripts/ | 289行 | 重建索引 |
| startup_check.py | memory_system/scripts/ | 222行 | 6项启动检查 |
| **Supermemory 云记忆** | 外部服务 | — | 4个容器 |

### 3.3 自动化守护

| 机制 | 工具 | 触发条件 | 失败处理 |
|------|------|---------|---------|
| 版本校验 | version_check.sh | 每次启动 | 阻断任务 |
| 每日日结 | daily_wrap.sh | 每天10:00 (launchd) | 飞书提醒 |
| 启动检查 | startup_check.py | 每次启动 | 警告不阻断 |
| 断档检测 | check_continuity.sh | 每日 | 飞书P0告警 |
| 记忆提取 | extract_memory.py | SESSION_END | 自动更新 |
| 质量检查 | check_quality.py | SESSION_END | 记录PENDING |
| 索引重建 | reindex.py | SESSION_END | 重建索引 |
| 月度review | monthly_review.sh | 每月 | 归档+清理 |

---

## 四、代码量统计

| 模块 | 文件数 | 总行数 |
|------|--------|--------|
| Skill 核心（__init__+core+tools+db+config） | ~25 | ~6,500 |
| 自学习（learning/） | ~15 | ~3,500 |
| 记忆系统（memory_system/） | ~10 | ~1,500 |
| 运维脚本（ops/） | ~15 | ~2,000 |
| 测试/脚本 | ~15 | ~3,000 |
| **总计** | **~80** | **~16,500** |

---

## 五、总体评估

### ✅ 做得好的

1. **架构分层清晰**：core/ → tools/ → db/ 三层分离，职责明确
2. **自学习闭环完整**：采集→分析→建议→CI→审批→应用→追踪，7步闭环
3. **记忆系统5层设计**：从自动守护到人工摘要，层层兜底
4. **配置化程度高**：阈值/关键词/清洗规则全部yaml化，无需改代码
5. **容错设计**：EventBus handler异常不阻断、DB连接失败静默跳过
6. **CI回归测试**：53用例100%通过，改代码后主动跑

### ⚠️ 需要关注的

1. **自学习数据量不足**：order_corrections 数据量少，5类建议可能很少触发
2. **SESSION_END协议执行不稳定**：日志有断档，记忆质量依赖AI自律
3. **效果追踪闭环未验证**：applied_changes 表可能还没有真实数据
4. **launchd plist 有硬编码占位符**：`__WORKSPACE__` 需要替换

### 🔴 潜在风险

1. **learn/ 双份代码**：skill内部有 learn/ 目录（stub），工作区有 learning/（真实），容易混淆
2. **core/ vs tools/ 重复逻辑**：core 模块动态导入 tools，但两者都有部分重复代码
3. **单点依赖**：所有模块都依赖 AWS RDS，断网时功能全部降级

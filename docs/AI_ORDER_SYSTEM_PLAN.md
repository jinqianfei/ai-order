# AI建单助手 — 系统总方案

> **最后更新**: 2026-06-14 12:30 GMT+8  
> **当前 Skill 版本**: v5.16.3（2026-06-16）  
> **状态**: 🟢 运行中

---

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AI建单助手 系统架构                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │  订单输入     │ →  │  主流程处理   │ →  │  华鼎模板输出 │                   │
│  │  Excel/图片   │    │  5 步流水线   │    │  31字段 Excel │                   │
│  │  PDF/文字     │    │              │    │              │                   │
│  └──────────────┘    └──────┬───────┘    └──────────────┘                   │
│                              │                                              │
│                    ┌─────────┴─────────┐                                    │
│                    │   EventBus (13事件) │                                    │
│                    └─────────┬─────────┘                                    │
│                              │                                              │
│  ┌──────────────┐    ┌──────┴───────┐    ┌──────────────┐                   │
│  │  定时任务     │    │  自学习模块   │    │  记忆系统     │                   │
│  │  5 个 launchd │ ←  │  采集→分析→  │ →  │  Supermemory │                   │
│  │              │    │  优化→闭环    │    │  + 本地文件   │                   │
│  └──────────────┘    └──────────────┘    └──────────────┘                   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────┐        │
│  │                     数据库 (AWS RDS PostgreSQL)                    │        │
│  │  product_sku (1832) | store_list (3327) | product_name_alias (30) │        │
│  │  learning_events | order_corrections | layer_success_rate         │        │
│  └──────────────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、订单处理主流程（v5.16.3）

### 核心流水线

```
Step 1: tools_parse()          LLM 解析订单 → 原始 JSON
         ↓
Step 2: tools_transform()      规则库标准化 → 统一 JSON
         ↓
Step 3: _match_store()  ⚠️     门店匹配（6层）→ 用户确认
         ↓
Step 4: _match_sku()    ⚠️     SKU 映射（6层）→ 用户确认
         ↓
Step 5: _generate_template()   华鼎 31 字段出库单 Excel
```

### Step 3: 门店匹配（6 层）

| 层 | 方法 | 输入 | 置信度 |
|----|------|------|--------|
| Layer 0 | 辅助信息匹配 | 手机号/收货人/地址 | 0.95 |
| Layer 1 | 客户公司精确匹配 | customer_company → owner_name | 0.90 |
| Layer 2 | 门店名称精确匹配 | store_name 完全一致 | 0.90 |
| Layer 3 | 门店名称模糊匹配 | 相似度 + 关键词交叉 | 0.70+ |
| Layer 3.5 | 关键词交叉匹配（兜底） | 模糊匹配失败后的组合匹配 | 0.65+ |
| Layer 3.6 | 联系人姓名兜底 | contact_person 作为门店名重搜 | 0.60+ |

**必须用户确认**：所有匹配结果都返回 `need_store_confirm=True`，货主随门店一起确认。

### Step 4: SKU 映射（6 层）

| 层 | 方法 | 置信度 |
|----|------|--------|
| Layer 0 | 别名表精确匹配（product_name_alias） | 0.98 |
| Layer 1 | SKU 名/货主编码精确匹配 | 0.95 |
| Layer 1b | 去规格后精确匹配 | 0.93 |
| Layer 2 | 模糊匹配 + 规格校验 + 单位打分 | 0.80+ |
| Layer 2.5 | 全量相似度 + 关键词加成 | 0.85 max |
| Layer 3 | 分词关键词匹配 + 包含关系加成 | 0.70+ |

**阈值配置化（v5.16.3）**：26 处 SKU 硬编码 + 13 处门店硬编码已替换为 `threshold_config.yaml` 配置读取，支持自动调优。

### 确认点

| 步骤 | 确认内容 | 展示格式 |
|------|---------|---------|
| Step 3 | 门店 + 货主 | 候选列表，用户选择 |
| Step 4 | SKU 映射 | 9 列映射对照表（已匹配+未匹配全展示） |

---

## 三、自学习闭环系统（v2.0）

### 数据流

```
用户操作（确认/纠正/取消）
         ↓
EventBus.emit()（13 个事件类型）
         ↓
collector.py 订阅 → 写入 learning_events 表
         ↓
┌────────────────────────────────────────┐
│           定时分析层                     │
│                                        │
│  daily_summary.py（每天 10:05）         │
│    → 统计 order_corrections            │
│    → 高频纠正 ≥2 次 → 别名建议         │
│                                        │
│  analyze_data.py（按需 / 周报触发）      │
│    → 各层成功率统计                     │
│    → 失败模式聚类                       │
│    → 阈值调优建议                       │
└────────────────┬───────────────────────┘
                 ↓
improver.py（生成优化建议）
         ↓
┌────────────────────────────────────────┐
│           自动优化层                     │
│                                        │
│  auto_apply=true 时：                   │
│    → 高置信度纠正 → 自动加别名表         │
│    → 阈值变更 → 写入 threshold_config   │
│    → CI 回归通过 → 生效                 │
│                                        │
│  auto_apply=false 时：                  │
│    → 生成建议报告，人工审核              │
└────────────────────────────────────────┘
```

### 13 个事件类型

| 事件 | 触发时机 | 数据用途 |
|------|---------|---------|
| `store_matched` | 门店匹配成功 | 层成功率统计 |
| `store_corrected` | 用户纠正门店 | 门店匹配优化 |
| `sku_matched` | SKU 匹配成功 | 层成功率统计 |
| `sku_confirm_needed` | SKU 需确认（置信度 <80%） | 低置信度分析 |
| `sku_confirmed` | 用户确认 SKU | 确认率统计 |
| `sku_corrected` | 用户纠正 SKU | 别名表候选 |
| `order_processed` | 订单完成 | 整体成功率 |
| `order_cancelled` | 订单取消 | 失败分析 |
| `alert_raised` | 告警触发 | 异常监控 |
| `mapping_failed` | 映射失败 | 未匹配分析 |
| `unknown_field_detected` | 检测到未知字段 | 解析规则扩展 |
| `unmatched_sku_keyword` | 未匹配 SKU 关键词 | 关键词库扩展 |
| `cleaning_rule_gap` | 清洗规则缺口 | 清洗规则补充 |

### 配置文件（v2 拆分）

| 文件 | 用途 |
|------|------|
| `config/threshold_config.yaml` | SKU/门店匹配阈值（28 项）+ 自动调优参数 |
| `config/cleaning_config.yaml` | 商品名清洗规则 |
| `config/keywords_config.yaml` | 关键词权重配置 |
| `config/analysis_config.yaml` | 分析阈值（成功率告警线等 8 项） |

---

## 四、定时任务清单

| # | 任务名 | 触发时间 | 脚本 | 功能 | 状态 |
|---|--------|---------|------|------|------|
| 1 | **daily-wrap** | 每天 10:00 | `ops/daily_wrap.sh` | 日结报告：断档检测 + 昨天数据汇总 + 飞书推送 | 🟢 已修复 DB 连接 |
| 2 | **daily-alias-summary** | 每天 **10:05** | `learning/scripts/daily_summary.py` | 自学习别名汇总：高频纠正 → 别名建议 | 🟢 已错开 5 分钟 |
| 3 | **phase3-maintenance** | 每周日 03:00 | `ops/phase3_maintenance.sh` | 记忆系统维护：索引重建 + MEMORY.md 提取 + 质量检查 | 🟢 正常 |
| 4 | **auto-git** | 持续运行 | `ops/auto_git_skill.sh` | fswatch 监控 skill 文件变更 → 自动 commit + push | 🟢 已修复路径 |
| 5 | **OpenClaw Gateway** | 持续运行 | `ai.openclaw.gateway` | OpenClaw 网关服务 | 🟢 正常 |

### 定时任务时间线

```
00:00 ───────────────────────────────────────────
03:00  ■ phase3-maintenance（每周日）
       │  索引重建 + MEMORY.md 提取 + 质量检查
       │
10:00  ■ daily-wrap（每天）
       │  断档检测 + 昨天数据汇总 + 飞书推送
       │
10:05  ■ daily-alias-summary（每天）
       │  order_corrections 统计 + 别名建议
       │
全天   ■ auto-git（持续）
       │  fswatch 监控 → 自动 commit
       │
全天   ■ OpenClaw Gateway（持续）
       │  网关服务
       │
24:00 ───────────────────────────────────────────
```

---

## 五、记忆系统

### 分层架构

| 层 | 存储 | 用途 | 触发 |
|----|------|------|------|
| L1 工作记忆 | 对话上下文 | 当前会话 | 自动 |
| L2 短期记忆 | Supermemory 云端 | 跨会话偏好/事实 | `supermemory_store` |
| L3 长期记忆 | MEMORY.md | 版本/会话摘要/决策 | 每次会话结束 |
| L4 项目记忆 | memory/projects/ | 项目级详细记录 | 按需 |
| L5 技能记忆 | skills/ | Skill 代码+配置 | 代码变更时 |

### Supermemory 容器路由

| 信息类型 | containerTag |
|---------|--------------|
| 订单、报价、商品、客户 | `ai_order` |
| 客服问答、FAQ | `ai_kefu` |
| 供应链、库存、产能 | `supply_chain` |
| 其他日常 | `openclaw_main` |

---

## 六、数据库架构

### 连接配置

```
Host: agenthub-db.cjys0msc4x8s.ap-southeast-1.rds.amazonaws.com
Port: 5432
Database: neo
User: agenthub
Password: $DB_PASSWORD（环境变量）
```

### 核心业务表

| 表名 | 行数 | 主键 | 用途 |
|------|------|------|------|
| `product_sku` | 1832 | (sku_code, shipper_id) | SKU 主表（12 货主） |
| `store_list` | 3327 | — | 门店列表 |
| `product_name_alias` | 30 | (order_product_name, shipper_id) | 商品名别名映射 |
| `warehouse_code_mapping` | — | — | 仓库编码 |
| `customer` | — | — | 货主信息 |

### 自学习表

| 表名 | 用途 |
|------|------|
| `learning_events` | 原始事件采集 |
| `order_corrections` | 用户纠正记录 |
| `layer_success_rate` | 各层成功率统计 |
| `sku_mapping_history` | SKU 映射历史 |

---

## 七、货主-品牌对照（12 个）

| 货主公司 | 品牌 | shipper_id | SKU 数 | 门店数 |
|---------|------|-----------|--------|--------|
| 盐城市创宇食品有限公司 | — | HZ2024061300001 | 640 | 257 |
| 河南上黎供应链管理有限公司 | 制茶青年 | HZ2023061500002 | 226 | 416 |
| 江西升创餐饮管理服务有限公司 | — | HZ2025122000013 | 214 | 68 |
| 郑州市必德供应链管理有限公司 | 廖朵朵 | HZ2024091100001 | 146 | 864 |
| 闻风达（西安）供应链管理有限公司 | — | HZ2025032700001 | 127 | 271 |
| 郑州洛点餐饮管理有限公司 | — | HZ2026000001 | 102 | 298 |
| 安徽洪通通供应链管理有限责任公司 | — | HZ2023101200002 | 100 | 421 |
| 杭州麻溜滴供应链有限公司 | — | HZ2024080200002 | 94 | 136 |
| 桐乡市峰杰餐饮管理服务有限公司 | — | HZ2026020300004 | 54 | 5 |
| 桐乡市峰杰餐饮管理服务有限公司 | — | HZ2023061500003 | 59 | 0 |
| 哈尔滨市梓茂食品有限公司 | — | HZ2025032400001 | 47 | 499 |
| 济南槐革弗澳辰食品供应链经营部 | — | HZ2026012600005 | 23 | 92 |

---

## 八、版本历史（近期）

| 版本 | 日期 | 关键变更 |
|------|------|---------|
| **v5.16.1** | 2026-06-14 | 匹配阈值配置化 + 自动调优（26+13 处硬编码替换） |
| v5.16.0 | 2026-06-14 | 自学习闭环 v2.0（事件总线扩展至 13 个，配置拆分） |
| v5.15.4 | 2026-06-12 | P1 多门店 confirmed_store 跨门店泄漏修复 |
| v5.15.2 | 2026-06-12 | store_corrected 误触发修复 + 自学习硬编码全修 |
| v5.14.0 | 2026-06-11 | 单位+SKU 绑定打分（统一 `_compute_match_score`） |
| v5.13.3 | 2026-06-11 | 清洗函数边界修复（果糖- / -果糖） |

---

## 九、文件结构

```
ai-order/
├── skills/
│   └── skill_order_to_huading_template/    # 主 Skill（v5.16.3）
│       ├── __init__.py                      # 主入口（execute()）
│       ├── VERSION                          # 版本号
│       ├── CHANGELOG.md                     # 变更日志
│       ├── SKILL.md                         # Skill 文档
│       └── tools/
│           ├── _order_parser.py             # Step 1: LLM 解析
│           ├── _field_transformer.py        # Step 2: 规则标准化
│           ├── _store_matcher.py            # Step 3: 门店匹配（6层）
│           ├── _sku_mapper.py               # Step 4: SKU 映射（6层）
│           └── _template_generator.py       # Step 5: 模板生成
│
├── learning/                                # 自学习模块（v2）
│   ├── collector.py                         # 事件采集器（13 事件订阅）
│   ├── improver.py                          # 优化建议生成
│   ├── modifier.py                          # 自动修改执行
│   ├── feedback_parser.py                   # 反馈解析
│   ├── adapter.py                           # 数据适配器
│   ├── schema.sql                           # DB Schema
│   ├── config/
│   │   ├── threshold_config.yaml            # 匹配阈值（28 项）
│   │   ├── cleaning_config.yaml             # 清洗规则
│   │   ├── keywords_config.yaml             # 关键词权重
│   │   └── analysis_config.yaml             # 分析阈值
│   └── scripts/
│       ├── daily_summary.py                 # 每日别名汇总
│       ├── analyze_data.py                  # 数据分析
│       └── history_replay.py                # 历史回放
│
├── ops/                                     # 运维脚本
│   ├── daily_wrap.sh                        # 每日日结（10:00）
│   ├── auto_git_skill.sh                    # 自动 git（持续）
│   ├── phase3_maintenance.sh                # 周维护（周日 03:00）
│   ├── check_continuity.sh                  # 断档检测
│   └── install_launchd.sh                   # launchd 安装
│
├── launchd/                                 # launchd plist
│   ├── com.ai-order.daily-wrap.plist        # 10:00
│   ├── com.ai-order.daily-alias-summary.plist  # 10:05
│   └── com.ai-order.phase3-maintenance.plist   # 周日 03:00
│
├── docs/                                    # 文档
│   ├── AI_ORDER_SYSTEM_PLAN.md              # ← 本文档（系统总方案）
│   ├── SELF_LEARNING_MODULE_PLAN.md         # 自学习模块方案
│   ├── SELF_LEARNING_CLOSED_LOOP_PLAN.md    # 闭环方案
│   └── SELF_LEARNING_V2_IMPLEMENTATION_SUMMARY.md
│
├── AGENTS.md          # Agent 配置
├── SOUL.md            # 人格/风格
├── IDENTITY.md        # 身份/数据库架构
├── TOOLS.md           # 工具配置
├── MEMORY.md          # 长期记忆
└── USER.md            # 用户信息
```

---

## 十、2026-06-14 修复记录

| 问题 | 根因 | 修复 |
|------|------|------|
| daily-wrap 和 daily-alias-summary 同时 10:00 触发 | 配置未错开 | daily-alias-summary 改为 10:05 |
| auto-git.plist 路径错误 | plist 写 `scripts/`，实际在 `ops/` | 修正为 `ops/auto_git_skill.sh` |
| daily_wrap.sh DB 连接 localhost | 脚本未更新为 RDS | 改为 `agenthub-db.cjys0msc4x8s.ap-southeast-1.rds.amazonaws.com:5432` |
| 三处修改均已 reload launchd 生效 | — | ✅ |

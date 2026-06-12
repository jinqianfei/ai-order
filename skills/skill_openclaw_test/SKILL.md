# skill-openclaw-test

OpenClaw Skill 通用测评框架。对任意 Skill 的修改版本进行对比测评，量化优化效果。

## 功能

- 加载测试数据集（订单文件 + Ground Truth 标注）
- 自动执行 Skill 映射逻辑（门店匹配 / SKU 映射）
- 对比新旧版本输出差异
- 生成量化测评报告（准确率、低置信度改善、未匹配分析）
- 支持多轮迭代优化 → 二次测评

## 适用场景

- Skill 修改后验证优化效果（如 v5.4 → v5.5）
- 新版本上线前的回归测试
- 多分支方案的横向对比

---

## 1. 测评所需文件

### 1.1 测试数据集（test_data/）

每个测试样本为一个 JSON 文件，包含：

```json
{
  "test_id": "test_001",
  "order_file": "xxx.xlsx",
  "order_format": "huading_standard",
  "store": {
    "name": "沛县廖朵朵",
    "ground_truth_store_code": "KH2024100600109",
    "ground_truth_owner_code": "HZ2024091100001"
  },
  "items": [
    {
      "seq": 1,
      "product_name": "云端小王子（20个/件）",
      "spec": "20个/件",
      "quantity": 1,
      "unit": "件",
      "ground_truth": {
        "sku_code": "SK251118000084",
        "sku_name": "蓝云朵",
        "unit": "盒",
        "unit_type": "小单位"
      }
    }
  ]
}
```

**构建方式**：
1. 收集真实订单文件，放入 `orders/` 目录
2. 对每个订单，手工标注 Ground Truth（从数据库查真实 SKU）
3. 保存为 `test_data/test_set_XXX.json`

### 1.2 测试数据集分类

| 文件 | 用途 | 说明 |
|------|------|------|
| `test_set_A_history.json` | 历史订单回归测试 | 已经处理过的真实订单 |
| `test_set_B_new_customer.json` | 新客户泛化测试 | 之前没见过的客户 |
| `test_set_C_boundary_cases.json` | 边界case测试 | 特殊规格、别名、疑难商品 |
| `test_set_D_blind_test.json` | 盲测 | 无 Ground Truth，用于生产验证 |

### 1.3 Ground Truth 构建方法

```python
# 通过已知信息查数据库，构建 Ground Truth
from tools.sku_mapper import map_sku
from tools.store_matcher import match_store

# 1. 门店匹配（已知门店名，查 store_list）
store_result = match_store(store_name="沛县廖朵朵", db_config=DB_CONFIG)
owner_code = store_result["matched_store"]["owner_code"]

# 2. SKU 映射（人工确认商品名对应哪个 SKU）
sku_result = map_sku(owner_code, "云端小王子（20个/件）", db_config=DB_CONFIG)
# 人工确认结果是否正确，填充 ground_truth
```

---

## 2. 测评脚本

### 2.1 执行测评

```bash
# 方式1：直接运行测评脚本
python scripts/re_evaluate_skill.py \
  --old-version v5.4 \
  --new-version v5.5 \
  --test-data test_data/test_set_A.json \
  --db-config config/db_config.yaml \
  --output report.md

# 方式2：通过 Skill API
from skills.skill_openclaw_test import SkillTester

tester = SkillTester(
    db_config={"host": "localhost", "port": 5432, "database": "neo", "user": "jinqianfei"},
    test_data_dir="test_data/"
)

result = tester.evaluate(
    skill_path="skills/skill_order_to_huading_template/",
    old_version="v5.4",
    new_version="v5.5",
    test_sets=["A", "B", "C"]
)
```

### 2.2 测评流程

```
Step 1: 加载测试数据集
         ↓
Step 2: 对每个测试样本，执行：
         → store_matcher.match_store() → 获取 owner_code
         → sku_mapper.map_sku() → 获取 SKU 映射结果
         ↓
Step 3: 对比 Ground Truth 计算指标：
         - 匹配率 = 命中数 / 总数
         - 置信度分布（<0.7 / 0.7-0.8 / ≥0.8）
         - 未匹配商品列表
         ↓
Step 4: 生成测评报告
         ↓
Step 5: 分析改善项 / 未改善项
         ↓
Step 6: 输出优化建议
```

---

## 3. 返回结果

### 3.1 量化指标

```json
{
  "evaluation_date": "2026-06-02",
  "skill_version": "v5.5",
  "total_tests": 609,
  "matched": 600,
  "unmatched": 9,
  "accuracy": "98.5%",
  "confidence_distribution": {
    "high": {"≥0.8": 598, "占比": "98.2%"},
    "medium": {"0.7-0.8": 2, "占比": "0.3%"},
    "low": {"<0.7": 0, "占比": "0%"}
  },
  "improved_items": [
    {
      "product_name": "免浆巴沙鱼片",
      "store": "鱼你幸福（深圳店）",
      "old_confidence": 0.68,
      "new_confidence": 0.88,
      "improvement": "+0.20",
      "reason": "Layer 3 包含关系加成 0.25"
    }
  ],
  "regressed_items": [],
  "unmatched_items": [
    {
      "product_name": "鱼你幸福金汤酱料",
      "store": "广西平果店",
      "reason": "数据库中无此 SKU"
    }
  ]
}
```

### 3.2 测评报告格式

```markdown
# Skill v5.5 测评报告（v5.4 → v5.5 优化验证）

## 整体准确率

| 指标 | v5.4 | v5.5 | 变化 |
|------|------|------|------|
| 总测试数 | 609 | 609 | 不变 |
| 高置信度(≥0.8) | 594 (97.5%) | **598 (98.2%)** | +4商品 |
| 低置信度(<0.8) | 6 (1.0%) | **2 (0.3%)** | -4商品 |
| 未匹配 | 9 (1.5%) | **9 (1.5%)** | 不变 |

## 改善商品

| 商品名称 | 门店 | v5.4置信度 | v5.5置信度 | 改善 | 原因 |
|----------|------|-----------|-----------|------|------|
| 免浆巴沙鱼片 | 鱼你幸福（深圳店） | 0.68 | **0.88** | ✅ +0.20 | Layer 3 加成 |

## 未匹配商品分析

| 商品名称 | 原因 | 建议解决方案 |
|----------|------|-------------|
| 鱼你幸福金汤酱料 | 数据库中无此 SKU | 通过别名表补充 |
```

---

## 4. 如何改进

### 4.1 分析框架

```
未匹配商品 → 分类 → 根因 → 解决方案

分类：
├── A 类：数据库缺少该 SKU（需补充 product_sku）
├── B 类：商品名差异大但语义相近（需优化匹配算法）
├── C 类：规格表达不一致（需标准化规则）
├── D 类：别名未收录（需补充 product_name_alias）
└── E 类：订单录入错误（需 LLM 纠错）
```

### 4.2 改进优先级

| 优先级 | 类型 | 改善商品数 | 建议 |
|--------|------|-----------|------|
| P0 | A 类未匹配 | 多 | 补充数据库 SKU |
| P1 | D 类低置信 | 4个+ | 补充别名表 |
| P2 | B/C 类模糊匹配 | 视情况 | 优化 Layer 2/3 算法 |

---

## 5. 二次测评

### 5.1 流程

```
第1轮测评（v5.x）→ 发现问题 → 修改代码 → 第2轮测评（v5.x+1）
         ↓
    量化改善效果
         ↓
    确认无回归
```

### 5.2 回归测试

每次测评必须包含：
1. **历史订单准确率不下降**（原有高置信商品仍高置信）
2. **新改善商品持续改善**（避免优化 A 导致 B 回归）
3. **边界 case 覆盖**：确保之前未匹配的商品有改善

```python
def regression_check(old_results, new_results):
    """检查是否有回归"""
    regressions = []
    for item in old_results:
        if item["confidence"] >= 0.8 and new_results[item["id"]]["confidence"] < 0.8:
            regressions.append(item)
    return regressions
```

---

## 6. 文件结构

```
skill_openclaw_test/
├── SKILL.md              # 本文件
├── __init__.py
├── config/
│   ├── db_config.yaml    # 数据库配置（需手动填写真实值）
│   └── test_config.yaml  # 测评配置
├── scripts/
│   ├── run_evaluation.py # 主测评脚本
│   ├── build_test_set.py # Ground Truth 构建工具
│   └── gen_report.py     # 报告生成
├── docs/
│   ├──测评方法论.md      # 详细测评方法
│   ├──数据集构建指南.md  # 如何构建测试集
│   └──改进分析指南.md    # 如何分析改善项
└── test_data/
    ├── README.md         # 测试数据集说明
    ├── test_set_A_history.json
    ├── test_set_B_new_customer.json
    ├── test_set_C_boundary.json
    └── sample_ground_truth.json
```

---

## 7. 配置项（db_config.yaml）

```yaml
db:
  host: localhost
  port: 5432
  database: neo
  user: jinqianfei
  # password: 填写你的密码

test:
  min_confidence_high: 0.8
  min_confidence_medium: 0.7
  confidence_threshold_warn: 0.8
```

---

## 8. 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-06-03 | 初版，基于 skill_order_to_huading_template v5.4→v5.5 测评经验 |
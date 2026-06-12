# 测试数据集说明

## 数据集文件

| 文件 | 说明 | 用途 |
|------|------|------|
| `test_set_A_history.json` | 历史订单（已有 Ground Truth） | 回归测试 |
| `test_set_B_new_customer.json` | 新客户订单 | 泛化能力测试 |
| `test_set_C_boundary.json` | 边界 case | 疑难商品 |
| `test_set_D_blind.json` | 盲测（无 GT） | 生产验证 |

## Ground Truth 格式

```json
{
  "test_id": "A001",
  "order_file": "沛县廖朵朵订单.xlsx",
  "order_format": "huading_standard",
  "stores": [
    {
      "store_name": "沛县廖朵朵",
      "ground_truth_store_code": "KH2024100600109",
      "ground_truth_owner_code": "HZ2024091100001",
      "ground_truth_warehouse_code": "C2024091100001",
      "items": [
        {
          "seq": 1,
          "product_name": "云端小王子（20个/件）",
          "spec": "20个/件",
          "quantity": 1,
          "unit": "件",
          "ground_truth_sku_code": "SK251118000084",
          "ground_truth_sku_name": "蓝云朵",
          "ground_truth_unit": "盒",
          "ground_truth_unit_type": "小单位"
        }
      ]
    }
  ]
}
```

## 构建 Ground Truth 的方法

### 1. 通过已知门店查 store_list

```python
from tools.store_matcher import match_store

store_result = match_store(
    store_name="沛县廖朵朵",
    db_config={"host": "localhost", "port": 5432, "database": "neo", "user": "jinqianfei"}
)
print(store_result["matched_store"]["owner_code"])
# HZ2024091100001
```

### 2. 通过已知的货主ID查询 product_sku

```python
import psycopg2

conn = psycopg2.connect(
    host="localhost", port=5432, database="neo",
    user="jinqianfei", password="YOUR_DB_PASSWORD"
)
cur = conn.cursor()
cur.execute("""
    SELECT sku_code, sku_name, unit, unit_type
    FROM product_sku
    WHERE shipper_id = 'HZ2024091100001'
      AND sku_name LIKE '%云端小王子%'
""")
print(cur.fetchall())
```

### 3. 使用 alias 表查别名

```python
cur.execute("""
    SELECT a.order_product_name, p.sku_code, p.sku_name
    FROM product_name_alias a
    JOIN product_sku p ON p.sku_name = a.system_product_name
    WHERE a.shipper_id = 'HZ2024091100001'
      AND a.order_product_name LIKE '%小王子%'
""")
```
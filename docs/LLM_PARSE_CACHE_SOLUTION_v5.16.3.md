# LLM 解析缓存方案 — v5.16.3

> **日期**：2026-06-16
> **触发问题**：端到端测试卡住 + "Repetitive tool calls" 报错
> **方案选择**：方案 A — 实例级内存缓存

---

## 问题背景

### 1. 端到端测试跑不通

`e2e_v5140.py` 试图走完整 `execute()` 流程，但卡在 Step 1 的 LLM 调用：

```
execute(order.xlsx)
  → Step 1: tools_parse()      ← LLM 解析 Excel → 卡住（timeout 60s 不够）
  → Step 2: tools_transform()
  → ...
```

**根因**：
- `OpenClawProvider` 通过 `subprocess.run(["openclaw", "infer", "model", "run", ...])` 调用 agent 自身的 LLM
- 原始 timeout 60 秒，复杂 Excel 解析需要 80-100 秒
- stderr 被 `capture_output=True` 吞掉，看不到报错
- `from config import` 被 `skill_ops_monitor/config.py` 抢先，导致模块导入冲突

### 2. "Repetitive tool calls detected" 报错

```
<400> InternalError.Algo.InvalidParameter: Repetitive tool calls detected
```

**根因**：Qwen 模型检测到对话历史中大量重复的 tool call（同一 Excel 文件被反复调 LLM 解析），触发死循环防护。

**本质**：`execute()` 每次调用都重新解析同一个 Excel 文件，因为：
- 第 1 次：解析 → 门店匹配 → 返回 need_store_confirm
- 第 2 次：**重新解析同一个 Excel** → SKU 映射 → 生成模板
- 多门店场景甚至需要 3-4 次重复解析

---

## 解决方案

### 方案对比

| 方案 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| **A: 实例级内存缓存** | `_parse_cache` 字典，key=文件路径 | 改动小、效果好、无需外部依赖 | 重启丢失 |
| B: 文件级缓存 | 存 JSON 到 `.cache/` 目录 | 持久化 | 文件管理复杂 |
| C: 测试 fixture | 录 LLM 响应，回放 | 测试速度快 | 只解决测试问题 |

**选择**：方案 A（实例级内存缓存）

---

## 实现细节

### 修改文件

1. `skills/skill_order_to_huading_template/__init__.py`
2. `skills/skill_order_to_huading_template/core/generator.py`
3. `skills/skill_order_to_huading_template/tools/_template_generator.py`
4. `learning/llm/openclaw.py`

### 核心代码（__init__.py）

```python
class OrderToHuadingTemplate:
    def __init__(self, db_config, output_dir=None):
        # ... 原有初始化 ...
        
        # ── LLM 解析结果缓存（同一文件不重复调 LLM）──
        self._parse_cache: Dict[str, Dict] = {}
    
    def execute(self, order_input=None, ...):
        # ── 解析缓存 key（文件路径标准化）──
        _cache_key = os.path.abspath(order_input) if order_input and os.path.exists(str(order_input)) else None
        
        if order_data_cache:
            order_data = order_data_cache
            extracted_from = order_data.get("_extracted_from", ...)
        elif _cache_key and _cache_key in self._parse_cache:
            # 命中缓存，跳过 LLM 解析
            order_data = copy.deepcopy(self._parse_cache[_cache_key])
            order_type = order_data.get("_order_type", "excel")
            extracted_from = f"{order_type}_cached"
            print(f"[INFO] 解析缓存命中: {_cache_key}", flush=True)
        elif order_type == "auto":
            order_type = self._detect_input_type(order_input)
        
        # ... 原有解析逻辑 ...
        
        # ── 写入解析缓存（同一文件下次不再调 LLM）──
        if _cache_key and _cache_key not in self._parse_cache and order_data:
            _cached = copy.deepcopy(order_data)
            _cached["_order_type"] = order_type
            _cached["_cached_at"] = time.time()
            self._parse_cache[_cache_key] = _cached
            print(f"[INFO] 解析结果已缓存: {os.path.basename(_cache_key)}", flush=True)
```

### 模块导入冲突修复

**问题**：`from config import _get_huading_fields` 被 `skill_ops_monitor/config.py` 抢先

**解决**：改用 `importlib.util.spec_from_file_location` 显式路径导入

```python
import importlib.util as _ilu
_this_dir = os.path.dirname(os.path.abspath(__file__))

_cfg_spec = _ilu.spec_from_file_location(
    "_local_config", 
    os.path.join(_this_dir, "config", "__init__.py"))
_cfg_mod = _ilu.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(_cfg_mod)
_get_huading_fields = _cfg_mod._get_huading_fields
```

### OpenClawProvider timeout 提升

```python
# learning/llm/openclaw.py
result = subprocess.run(
    cmd,
    capture_output=True, text=True, timeout=180  # 60s → 180s
)

if result.returncode != 0:
    print(f"[OpenClawProvider] exit={result.returncode}, stderr={result.stderr[:500]}", flush=True)
```

---

## 测试结果

### 单门店：洪洪通_1店1项.xlsx

| 步骤 | 耗时 | 说明 |
|------|------|------|
| Step 1: LLM 解析 | 53.7s | 首次解析，写入缓存 |
| Step 2: 门店确认 → SKU映射 → 生成模板 | **6.4s** | ✅ 缓存命中 |

**提速**：Step 2 从 ~50s 降至 **6.4s**，快 **8 倍**

### 多门店：天津仓_2店11项.xlsx

| 步骤 | 耗时 | 说明 |
|------|------|------|
| Step 1: LLM 解析 | 78.6s | 识别出 2 个门店 |
| 确认门店 A（塘沽万达） | 6.1s | ✅ 缓存命中 |
| 确认门店 B（天宫院） | 12.7s | ✅ 缓存命中 |
| SKU 映射 + 生成模板 | 22.3s | ✅ 缓存命中 |
| **总计** | **119.8s** | **2 分钟** |

**结果**：
- ✅ 2 个门店全部确认成功
- ✅ 11 个商品 SKU 全部命中（0 未匹配）
- ✅ 货主：HZ2024061300001（创宇）
- ✅ 华鼎出库单已生成

**如果没有缓存**：同样流程需要 4 次 LLM 调用 = ~312s（5 分钟+）

---

## CI 回归测试

```
✅ 53/53 SKU 回归测试全过
✅ version_check.sh 7 处真相源一致
```

---

## 版本更新

**v5.16.2 → v5.16.3**

已更新文件：
- VERSION
- SKILL.md
- CHANGELOG.md
- __init__.py
- AGENTS.md
- MEMORY.md
- TOOLS.md
- memory/projects/ai-order/PROJECT.md
- memory/projects/ai-order/skills/INDEX.md
- docs/UPWORK_PROFILE_GUIDE.md
- memory_system/scripts/test_memory_closed_loop.py
- skills/.../README.md
- skills/.../scripts/test_self_learning_closed_loop_contract.py

---

## 对话中的实际效果

以前：确认门店后还要再等一遍 LLM 解析 Excel（~50s）  
现在：直接走缓存，秒出 SKU 映射结果（~6s）

用户体验显著提升。

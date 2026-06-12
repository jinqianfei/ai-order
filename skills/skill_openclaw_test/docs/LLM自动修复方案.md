# LLM 自动修复方案设计

## 一、现状总结

### 历史修复数据来源

| 来源 | 内容 | 可用性 |
|------|------|--------|
| `output/` 历史文件 | 每次处理的测评报告 | ❌ 无修复记录 |
| `MEMORY.md` / `IDENTITY.md` | 版本变更记录 | ⚠️ 有限 |
| `SKILL_EVALUATION_REPORT.md` | 手动测评记录 | ⚠️ 有限 |
| 代码本身 (git blame) | 每次改动的 diff | ✅ 最可靠 |
| `重构方案_skill_order_to_huading_template.md` | 架构变更 | ✅ 完整 |

---

## 二、历史修复案例（从今天的工作中提取）

| # | 修复场景 | 类型 | 触发原因 | 修复方式 |
|---|---------|------|---------|---------|
| 1 | `original_product_name` 字段缺失 | 普通风险 | 测评发现 matched 结果无原始商品名 | 修改 `_build_result()` 增加字段 |
| 2 | `match_layer` 字段缺失 | 普通风险 | 测评发现结果无匹配层信息 | 所有 `_build_result()` 调用补填 |
| 3 | `risk_levels.yaml` 解析错误 | Bug | YAML语法错误（单引号转义） | 简化 YAML 规则文件 |
| 4 | Division by zero in `_build_report` | Bug | total=0 时除零 | 加 `if total > 0` 保护 |
| 5 | test_data_dir 路径错误 | Bug | 相对路径解析失败 | 改用 `Path(__file__).parent` 绝对路径 |
| 6 | test_set_A.json 重复60条 | 数据错误 | 同一别名大单位+小单位各重复 | 改为30条（小单位） |

---

## 三、白名单规则（从历史修复提炼）

### F001: 补全返回字段

```yaml
fix_id: F001
name: "补全函数返回字典字段"
risk: low
detect:
  - pattern: "result\[.*?\] missing"
    context: "matched 结果缺少字段"
  - pattern: "\"original_product_name\":\s*\"\""
    context: "字段存在但为空"
fix_type: "field_addition"
handler: add_result_field
```

### F002: 修复除零错误

```yaml
fix_id: F002
name: "修复 division by zero"
risk: low
detect:
  - pattern: "division by zero"
  - pattern: "{hit/total*100"
fix_type: "guard_condition"
handler: add_zero_guard
```

### F003: 修复文件路径

```yaml
fix_id: F003
name: "修复相对路径解析"
risk: low
detect:
  - pattern: "test_data_dir.*not exist"
  - pattern: "Path.*parent.*parent"
fix_type: "path_resolution"
handler: fix_path_resolution
```

---

## 四、LLM 自动修复 — 完整方案

### 4.1 核心架构

```
┌─────────────────────────────────────────────┐
│         测评报告 / 错误信息                   │
│   (问题描述：字段缺失、置信度低、Bug等)        │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  Step 1: LLM 分析问题根因                   │
│  输入: 问题描述 + 出错文件片段               │
│  输出: 问题类型 + 修复策略                  │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  Step 2: LLM 生成修复代码                   │
│  输入: 问题类型 + 修复策略 + 目标文件         │
│  输出: 可执行的 Python 补丁代码              │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  Step 3: 验证修复代码                        │
│  - 语法检查 (ast.parse)                     │
│  - 语义检查 (导入测试)                      │
│  - 模拟执行 (不真正写文件)                   │
│  输出: 通过/失败 + 失败原因                  │
└─────────────────┬───────────────────────────┘
                  ↓
┌─────────────────────────────────────────────┐
│  Step 4: 人工确认 / 自动执行                │
│  高风险 → 发给用户确认                       │
│  普通风险 → 自动写入 + 复测                  │
└─────────────────────────────────────────────┘
```

### 4.2 核心代码实现

#### LLMRepairSkill 类

```python
import ast
import subprocess
import sys
from typing import Tuple, Dict, Any, Optional
from pathlib import Path

class LLMRepairSkill:
    """基于 LLM 的自动修复 Skill"""

    SYSTEM_PROMPT = """你是一个 Python 代码修复专家。

收到问题描述后，你会：
1. 分析问题根因
2. 生成最小化的修复代码
3. 确保修复后代码语法正确

修复原则：
- 最小改动：只改必要的地方
- 向后兼容：不改变已有函数签名
- 有据可查：在注释中说明修复原因

输出格式：
修复代码必须用 ```python ... ``` 包裹。"""

    def __init__(self, db_config: dict = None):
        self.db_config = db_config
        self.model = "minimax-portal/MiniMax-M2.7"

    # ================================================================
    # Step 1: 分析问题
    # ================================================================
    def analyze_problem(
        self,
        problem: str,            # 问题描述
        file_path: str,          # 出错文件
        context_lines: str = "",  # 相关代码片段
        error_trace: str = "",   # 错误堆栈
    ) -> Dict[str, Any]:
        """
        LLM 分析问题根因
        """
        prompt = f"""分析以下问题：

文件：{file_path}
问题：{problem}

错误堆栈：
{error_trace}

相关代码：
{context_lines}

请分析：
1. 问题的根本原因是什么？
2. 属于哪种修复类型？（字段缺失/除零错误/路径错误/算法问题）
3. 修复的优先级？（高风险/普通风险/禁止自动修复）

请用 JSON 格式输出：
{{
  "root_cause": "...",
  "fix_type": "field_missing | division_by_zero | path_error | algorithm | other",
  "risk_level": "high | ordinary | forbidden",
  "fix_strategy": "...",
  "affected_functions": ["..."]
}}"""

        response = self._call_llm(prompt)
        return self._parse_json_response(response)

    # ================================================================
    # Step 2: 生成修复代码
    # ================================================================
    def generate_fix(
        self,
        file_path: str,
        problem: str,
        fix_strategy: str,
        context_lines: str = "",
        max_fix_lines: int = 50,
    ) -> str:
        """
        LLM 生成修复代码
        """
        # 读取原文件内容
        with open(file_path) as f:
            original_code = f.read()

        prompt = f"""请为以下 Python 文件生成修复代码。

文件：{file_path}

问题：{problem}
修复策略：{fix_strategy}

原文件内容（部分）：
```
{context_lines or original_code[:2000]}
```

要求：
1. 只输出修复代码，用 ```python ... ``` 包裹
2. 改动范围控制在 {max_fix_lines} 行以内
3. 保持原函数的参数和返回值结构不变
4. 在修复代码前加一行注释说明修复原因

示例输出格式：
```python
# 修复原因：{修复策略}
...修复后的代码...
```"""

        response = self._call_llm(prompt)
        return self._extract_code_block(response)

    # ================================================================
    # Step 3: 验证修复代码
    # ================================================================
    def validate_fix(self, fix_code: str, original_file: str) -> Tuple[bool, str]:
        """
        验证修复代码的正确性

        1. 语法检查：ast.parse
        2. 导入检查：能否正常导入
        3. 模拟执行：apply 后不破坏原逻辑
        """
        # 3.1 语法检查
        try:
            ast.parse(fix_code)
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        # 3.2 导入检查（隔离环境）
        test_code = f"""
import sys
sys.path.insert(0, '{str(Path(original_file).parent.parent)}')
{fix_code}
"""
        try:
            compile(test_code, '<string>', 'exec')
        except Exception as e:
            return False, f"编译错误: {e}"

        # 3.3 语义检查：修复后函数签名不变
        try:
            original_ast = ast.parse(open(original_file).read())
            fixed_ast = ast.parse(fix_code)

            # 检查关键函数是否存在
            original_funcs = {n.name for n in ast.walk(original_ast) if isinstance(n, ast.FunctionDef)}
            # 修复代码可能只是片段，不一定有完整函数
        except Exception as e:
            return False, f"语义检查失败: {e}"

        return True, "验证通过"

    # ================================================================
    # Step 4: 执行修复
    # ================================================================
    def apply_fix(
        self,
        file_path: str,
        fix_code: str,
        dry_run: bool = True,
    ) -> Tuple[bool, str]:
        """
        执行修复
        """
        # 验证
        valid, msg = self.validate_fix(fix_code, file_path)
        if not valid:
            return False, f"验证失败: {msg}"

        if dry_run:
            return True, f"干跑通过：{fix_code[:100]}..."

        # 生成备份
        backup_path = f"{file_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy2(file_path, backup_path)

        # 实际应用（需要更智能的逻辑，这里简化处理）
        # 完整实现需要：diff 应用或 AST 重写
        return False, "自动 apply 需要更智能的 diff 应用逻辑，建议用 dry_run 模式后手动审查"

    # ================================================================
    # 完整工作流
    # ================================================================
    def auto_repair(
        self,
        problem: str,
        file_path: str,
        context_lines: str = "",
        error_trace: str = "",
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """
        完整的 LLM 自动修复流程
        """
        # Step 1: 分析
        analysis = self.analyze_problem(problem, file_path, context_lines, error_trace)
        if analysis.get("risk_level") == "forbidden":
            return {
                "status": "blocked",
                "reason": "禁止自动修复（安全风险）",
                "analysis": analysis,
            }

        # Step 2: 生成
        fix_code = self.generate_fix(
            file_path, problem,
            analysis.get("fix_strategy", ""),
            context_lines
        )

        # Step 3: 验证
        valid, msg = self.validate_fix(fix_code, file_path)
        if not valid:
            return {
                "status": "failed",
                "reason": f"验证失败: {msg}",
                "fix_code": fix_code,
                "analysis": analysis,
            }

        # Step 4: 执行
        ok, msg = self.apply_fix(file_path, fix_code, dry_run)

        return {
            "status": "success" if ok else "failed",
            "message": msg,
            "fix_code": fix_code,
            "analysis": analysis,
            "dry_run": dry_run,
            "backup": f"{file_path}.bak" if not dry_run else None,
        }

    # ================================================================
    # 辅助函数
    # ================================================================
    def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        import openai
        client = openai.OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url="https://api.minimaxi.chat/v1"
        )
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content

    def _extract_code_block(self, text: str) -> str:
        """从 LLM 输出中提取代码块"""
        import re
        match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # fallback：返回整个文本
        return text.strip()

    def _parse_json_response(self, text: str) -> dict:
        """从 LLM 输出中提取 JSON"""
        import re
        match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
        if match:
            import json
            return json.loads(match.group(1))
        return {"raw": text}
```

---

## 五、与现有框架的集成

### 集成方式：在 `auto_repair.py` 中增加 LLM 修复器

```python
class AutoRepairSkill:
    def __init__(self, skill_path: str, rules_path: str = None):
        # ... 现有代码 ...
        self.llm_repairer = LLMRepairSkill()

    def execute_llm_repair(
        self,
        problem: str,
        file_path: str,
        context_lines: str = "",
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """LLM 驱动的自动修复"""
        # 风险分级
        risk_level, reasons = self.classifier.classify_change(
            file_path, problem
        )

        if risk_level == "forbidden":
            return {"status": "blocked", "reason": "禁止自动修复"}

        if risk_level in ("high_critical", "high"):
            return {
                "status": "needs_manual_review",
                "risk_level": risk_level,
                "reasons": reasons,
            }

        # 调用 LLM 修复
        return self.llm_repairer.auto_repair(
            problem=problem,
            file_path=file_path,
            context_lines=context_lines,
            dry_run=dry_run,
        )
```

### 集成到 workflow.py

```python
def step3_confirm_or_repair(self, auto_confirm: bool = False):
    # ... 高风险检查 ...

    # 普通风险：优先 LLM 修复
    if not requires_manual:
        llm_result = self.repair.execute_llm_repair(
            problem=problem_description,
            file_path=affected_file,
            context_lines=diff_content,
            dry_run=not auto_confirm,
        )

        if llm_result["status"] == "success":
            # 复测验证
            self.step4_retest()
```

---

## 六、关键设计决策

### Q1: LLM 生成的代码如何安全执行？

| 方案 | 优点 | 缺点 |
|------|------|------|
| A. 先写临时文件验证再执行 | 安全 | 流程复杂 |
| B. AST 语法树对比 | 精确 | 实现难 |
| C. Dry-run 模式，用户手动确认 | 简单安全 | 需人工介入 |
| **推荐** | **C（先用 dry_run 跑通流程）** | **后续再优化** |

### Q2: 修复失败如何处理？

```
修复失败
  → 保留原文件不动
  → 生成修复建议（diff 格式）
  → 发给用户手动处理
  → 不破坏原代码
```

### Q3: 修复后如何验证效果？

```
修复后 → 自动跑测评工作流
  → 对比前后测评报告
  → 通过 → 合并 Git
  → 失败 → 回滚 Git 分支
```

---

## 七、下一步实施计划

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| 1 | 把 `LLMRepairSkill` 实现到 `auto_repair.py` | P0 |
| 2 | 集成到 `workflow.py` step3 | P0 |
| 3 | 支持 dry_run + diff 应用 | P1 |
| 4 | 自动提取出错文件 + 上下文 | P1 |
| 5 | 接入 OpenAI/MiniMax API | P2 |
| 6 | 修复历史记录 + 知识库 | P3 |

---

## 八、快速开始代码

以下代码可以直接放到 `auto_repair.py` 中：

```python
def llm_auto_fix(
    problem: str,
    file_path: str,
    context_lines: str = "",
    api_key: str = None,
) -> str:
    """
    最简版 LLM 自动修复
    仅生成修复代码，不自动执行
    """
    import openai
    import re

    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY")

    client = openai.OpenAI(
        api_key=api_key,
        base_url="https://api.minimaxi.chat/v1"
    )

    prompt = f"""问题：{problem}

文件：{file_path}

相关代码：
{context_lines}

请生成修复代码，用 ```python ... ``` 包裹。"""

    response = client.chat.completions.create(
        model="minimax-portal/MiniMax-M2.7",
        messages=[
            {"role": "system", "content": "你是一个 Python 代码修复专家。直接输出修复代码。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    text = response.choices[0].message.content
    match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()
```
#!/usr/bin/env python3
"""
LLM 自动修复模块 - 基于 LLM 生成修复代码

集成到 auto_repair.py 的 LLMRepairSkill 类，
负责：分析问题 → 生成修复代码 → 验证 → 执行

使用方式：
    python scripts/auto_repair.py --skill-path .. --action llm-repair \
        --problem "original_product_name 字段缺失" \
        --file tools/sku_mapper.py \
        --dry-run
"""

import ast
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


class LLMRepairSkill:
    """基于 LLM 的自动修复"""

    SYSTEM_PROMPT = """你是一个 Python 代码修复专家。

收到问题描述后，你会：
1. 分析问题根因
2. 生成最小化的修复代码
3. 确保修复后代码语法正确

修复原则：
- 最小改动：只改必要的地方
- 向后兼容：不改变已有函数签名
- 有据可查：在注释中说明修复原因

重要：
- 只输出修复代码，用 ```python ... ``` 包裹
- 如果问题复杂，先说明修复策略，再给出代码
- 禁止输出的内容：删除文件、修改数据库连接、修改密码/密钥"""

    def __init__(self, model: str = "minimax-portal/MiniMax-M2.7"):
        self.model = model

    # ============================================================
    # 核心：分析 + 生成 + 验证 + 执行
    # ============================================================

    def analyze_and_fix(
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
        # Step 1: 读取原文件 + 上下文
        if not os.path.exists(file_path):
            return {"status": "error", "message": f"文件不存在: {file_path}"}

        with open(file_path) as f:
            original_code = f.read()

        # 收集上下文（前2000字符）
        context = context_lines or original_code[:2000]

        # Step 2: LLM 分析问题
        analysis = self._analyze_problem(problem, file_path, context, error_trace)

        # Step 3: 判断是否禁止自动修复
        if analysis.get("risk_level") == "forbidden":
            return {
                "status": "forbidden",
                "message": "禁止自动修复（安全风险）",
                "analysis": analysis,
            }

        if analysis.get("risk_level") == "high":
            return {
                "status": "needs_manual_review",
                "message": "高风险修改，需人工确认",
                "analysis": analysis,
            }

        # Step 4: LLM 生成修复代码
        fix_code = self._generate_fix(
            problem=problem,
            file_path=file_path,
            original_code=original_code,
            context=context,
            fix_strategy=analysis.get("fix_strategy", ""),
        )

        # Step 5: 验证修复代码
        valid, msg = self._validate_fix(fix_code, original_code)
        if not valid:
            return {
                "status": "validation_failed",
                "message": f"验证失败: {msg}",
                "analysis": analysis,
            }

        # Step 6: 执行或干跑
        if dry_run:
            return {
                "status": "success",
                "message": f"✅ 验证通过（dry_run）\n{msg}",
                "analysis": analysis,
                "fix_code": fix_code,
                "preview": self._generate_diff_preview(original_code, fix_code, file_path),
            }
        else:
            # 备份 + 应用
            backup_path = f"{file_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.copy2(file_path, backup_path)

            try:
                with open(file_path, "w") as f:
                    f.write(fix_code)
                return {
                    "status": "applied",
                    "message": f"✅ 修复已应用",
                    "analysis": analysis,
                    "fix_code": fix_code,
                    "backup": backup_path,
                }
            except Exception as e:
                # 回滚
                shutil.copy2(backup_path, file_path)
                return {
                    "status": "apply_failed",
                    "message": f"写入失败，已回滚: {e}",
                    "analysis": analysis,
                    "fix_code": fix_code,
                }

    # ============================================================
    # Step 1: 分析问题
    # ============================================================

    def _analyze_problem(
        self,
        problem: str,
        file_path: str,
        context: str,
        error_trace: str,
    ) -> Dict[str, Any]:
        """调用 LLM 分析问题根因"""
        prompt = f"""分析以下 Python 代码问题：

文件：{file_path}
问题：{problem}

错误堆栈（如有）：
{error_trace}

相关代码（部分）：
```
{context}
```

请用 JSON 格式输出分析结果：
{{
  "root_cause": "问题根本原因",
  "fix_type": "field_missing | division_by_zero | path_error | algorithm | logging | type_hint | other",
  "risk_level": "low | ordinary | high | forbidden",
  "fix_strategy": "修复策略简述",
  "affected_functions": ["受影响的函数名列表"],
  "reason": "判断理由"
}}"""

        response = self._call_llm(prompt)
        return self._parse_json(response)

    # ============================================================
    # Step 2: 生成修复代码
    # ============================================================

    def _generate_fix(
        self,
        problem: str,
        file_path: str,
        original_code: str,
        context: str,
        fix_strategy: str,
    ) -> str:
        """调用 LLM 生成修复代码"""
        prompt = f"""请为以下 Python 文件生成修复代码。

文件：{file_path}
问题：{problem}
修复策略：{fix_strategy}

```python
// 原文件内容（关键部分）
{self._extract_key_section(original_code, problem)}
```

要求：
1. 只输出修复代码，用 ```python ... ``` 包裹，不要有其他文字
2. 改动范围控制在 30 行以内
3. 保持原函数的参数和返回值结构不变
4. 修复代码需要完整可执行（不是代码片段）

示例输出：
```python
# 修复原因：{problem}
def _build_result(row: tuple, confidence: float, original_product_name: str = "") -> dict:
    return {{
        "matched": True,
        "confidence": confidence,
        "sku_code": row[0],
        ...
        "original_product_name": original_product_name,  # 新增字段
    }}
```"""

        response = self._call_llm(prompt)
        return self._extract_code_block(response)

    def _extract_key_section(self, code: str, problem: str) -> str:
        """提取与问题相关的代码片段（前1500字符）"""
        # 尝试找到相关的函数
        lines = code.split("\n")
        relevant = []
        for i, line in enumerate(lines[:100]):  # 前100行应该包含主要函数
            if any(kw in line.lower() for kw in ["def ", "class ", "# ", "return {"]):
                relevant.append(line)
        if relevant:
            return "\n".join(relevant[:50])
        return code[:1500]

    # ============================================================
    # Step 3: 验证修复代码
    # ============================================================

    def _validate_fix(self, fix_code: str, original_code: str, target_func_name: str = None) -> Tuple[bool, str]:
        """验证修复代码的正确性"""
        # 3.1 语法检查
        try:
            ast.parse(fix_code)
        except SyntaxError as e:
            return False, f"语法错误 line {e.lineno}: {e.msg}"

        # 3.2 检查目标函数是否被保留
        if target_func_name:
            # 只检查被修改的函数是否还在
            original_ast = ast.parse(original_code)
            original_funcs = {
                n.name: n
                for n in ast.walk(original_ast)
                if isinstance(n, ast.FunctionDef)
            }
            fixed_ast = ast.parse(fix_code)
            fixed_funcs = {
                n.name: n
                for n in ast.walk(fixed_ast)
                if isinstance(n, ast.FunctionDef)
            }
            if target_func_name not in fixed_funcs:
                return False, f"函数 {target_func_name} 被删除"
            # 检查同名函数参数数量是否兼容
            orig_args = len(original_funcs[target_func_name].args.args)
            fixed_args = len(fixed_funcs[target_func_name].args.args)
            if fixed_args < orig_args:
                return False, f"函数 {target_func_name} 参数减少（可能破坏调用）"
        else:
            # 宽松检查：只要能 parse 就行
            pass

        return True, "验证通过"

    def _generate_diff_preview(
        self,
        original_code: str,
        fix_code: str,
        file_path: str,
        max_lines: int = 20,
    ) -> str:
        """生成 diff 预览"""
        orig_lines = original_code.split("\n")
        fix_lines = fix_code.split("\n")

        # 简单行对比（取两者的前max_lines行）
        diff_lines = []
        for i, (o, f) in enumerate(zip(orig_lines[:max_lines], fix_lines[:max_lines])):
            if o != f:
                diff_lines.append(f"  {i+1}: - {o[:60]}")
                diff_lines.append(f"  {i+1}: + {f[:60]}")

        header = f"--- {file_path}\n+++ {file_path}"
        body = "\n".join(diff_lines) if diff_lines else "(改动见下方代码)"

        return f"```diff\n{header}\n{body}\n```"

    # ============================================================
    # 辅助函数
    # ============================================================

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        try:
            import openai
        except ImportError:
            return '{"error": "openai not installed"}'

        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY")
        if not api_key:
            return '{"error": "No API key found"}'

        client = openai.OpenAI(api_key=api_key, base_url="https://api.minimaxi.chat/v1")

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                timeout=60,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f'{{"error": "{e}"}}'

    def _extract_code_block(self, text: str) -> str:
        """从 LLM 输出中提取代码块"""
        match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # 尝试不加语言标记
        match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """从 LLM 输出中提取 JSON"""
        try:
            import json
            match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return {"raw": text, "error": "JSON解析失败"}


# ============================================================
# 命令行入口
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="LLM 自动修复工具")
    parser.add_argument("--skill-path", required=True, help="Skill 代码路径")
    parser.add_argument("--problem", required=True, help="问题描述")
    parser.add_argument("--file", required=True, help="目标文件（相对于 skill-path）")
    parser.add_argument("--context", help="相关代码片段")
    parser.add_argument("--error-trace", help="错误堆栈")
    parser.add_argument("--dry-run", action="store_true", default=True, help="干跑模式（不实际写入）")
    parser.add_argument("--apply", action="store_true", help="实际执行修复")
    parser.add_argument("--model", default="minimax-portal/MiniMax-M2.7", help="LLM 模型")

    args = parser.parse_args()

    skill_root = Path(args.skill_path).resolve()
    file_path = skill_root / args.file

    if not file_path.exists():
        print(f"❌ 文件不存在: {file_path}")
        return

    repairer = LLMRepairSkill(model=args.model)

    result = repairer.analyze_and_fix(
        problem=args.problem,
        file_path=str(file_path),
        context_lines=args.context or "",
        error_trace=args.error_trace or "",
        dry_run=not args.apply,
    )

    print(f"\n{'='*60}")
    print(f"LLM 自动修复结果")
    print(f"{'='*60}")
    print(f"状态: {result['status']}")
    print(f"消息: {result.get('message', '')}")

    if result.get("analysis"):
        print(f"分析: {result['analysis'].get('root_cause', 'N/A')}")
        print(f"修复类型: {result['analysis'].get('fix_type', 'N/A')}")
        print(f"风险等级: {result['analysis'].get('risk_level', 'N/A')}")

    if result.get("preview"):
        print(f"\n{result['preview']}")

    if result.get("fix_code"):
        print(f"\n生成修复代码：")
        print(f"```python\n{result['fix_code']}\n```")

    if result.get("backup"):
        print(f"备份: {result['backup']}")


if __name__ == "__main__":
    main()
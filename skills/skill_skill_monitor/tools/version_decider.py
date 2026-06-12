#!/usr/bin/env python3
"""版本递增级别判断器"""
import re
from typing import List, Tuple

# 重大变化（需要 major 版本递增）
MAJOR_PATTERNS = [
    (r"删除|\brm\b|\bremove\b|\bdelete\b", "删除功能"),
    (r"拆分|\b重构\b.*架构|\b架构\b.*重构", "架构重构"),
    (r"数据库.*迁移|migration|schema.*change", "数据库迁移"),
    (r"接口.*变化|api.*break|break.*api", "接口变化"),
    (r"删除表|drop table|drop index", "删除数据库对象"),
]

# 中等变化（需要 minor 版本递增）
MINOR_PATTERNS = [
    (r"新增|\badd\b|\bnew\b|\bcreate\b|\binit\b", "新增功能"),
    (r"支持.*\bnew\b.*format|支持.*新格式", "新增支持格式"),
    (r"优化|\bimprove\b|\brefactor\b|\boptimize\b", "功能优化/重构"),
    (r"重构|\brefactor\b", "代码重构"),
    (r"数据库.*新增|alter table.*add|新增.*字段|新增.*表", "数据库变更"),
    (r"skill.*版本|version.*change", "版本更新说明"),
]

# 微小变化（patch 版本递增）
PATCH_PATTERNS = [
    (r"修复|\bfix\b|\bbugfix\b|\bhotfix\b", "Bug 修复"),
    (r"文档|\breadme\b|\bdoc\b|\bcomment\b|\b注释\b", "文档调整"),
    (r"格式|\bformat\b|\blint\b|\bprettier\b", "格式调整"),
    (r"配置|\bconfig\b.*yaml|\.yaml\b.*config", "配置调整"),
    (r"版本号|version.*bump|VERSION.*update", "版本号更新"),
]


def categorize_files(changed_files: List[str]) -> dict:
    """根据改动文件类型分类"""
    categories = {
        "code": [],      # .py 文件
        "config": [],    # .yaml, .json 配置
        "doc": [],       # .md 文档
        "sql": [],       # .sql
        "schema": [],    # 数据库 schema
        "other": [],
    }

    for f in changed_files:
        ext = f.split(".")[-1].lower()
        if ext in ("py", "js", "ts"):
            categories["code"].append(f)
        elif ext in ("yaml", "yml", "json", "toml", "ini", "cfg"):
            categories["config"].append(f)
        elif ext in ("md", "txt", "rst"):
            categories["doc"].append(f)
        elif ext in ("sql",):
            categories["sql"].append(f)
        elif "schema" in f.lower() or "migration" in f.lower():
            categories["schema"].append(f)
        else:
            categories["other"].append(f)

    return categories


def decide_version_bump(changed_files: List[str], diff_content: str = "", commit_msg: str = "") -> Tuple[str, str]:
    """
    根据改动文件+diff内容+commit消息判断版本变化级别。
    返回: (bump_type, reason)
    bump_type: 'patch' | 'minor' | 'major'
    reason: 变化原因说明
    """
    categories = categorize_files(changed_files)
    all_text = (diff_content + " " + commit_msg).lower()

    # 先检查 major
    for pattern, label in MAJOR_PATTERNS:
        if re.search(pattern, all_text, re.IGNORECASE):
            return "major", label

    # 再检查 minor
    for pattern, label in MINOR_PATTERNS:
        if re.search(pattern, all_text, re.IGNORECASE):
            return "minor", label

    # 检查 patch
    for pattern, label in PATCH_PATTERNS:
        if re.search(pattern, all_text, re.IGNORECASE):
            return "patch", label

    # 如果只有文档
    if categories["doc"] and not categories["code"]:
        return "patch", "文档更新"

    # 如果只有配置
    if categories["config"] and not categories["code"]:
        return "patch", "配置调整"

    # 只有代码变更但无明确模式 → minor
    if categories["code"]:
        return "minor", "代码变更（无特定类型）"

    return "patch", "微量调整"


def bump_version(current_version: str, bump_type: str) -> str:
    """
    根据 bump_type 递增版本号
    current_version: "5.8.0"
    bump_type: 'patch' | 'minor' | 'major'
    返回: 新版本号
    """
    try:
        parts = current_version.split(".")
        while len(parts) < 3:
            parts.append("0")
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2])

        if bump_type == "major":
            major += 1
            minor = 0
            patch = 0
        elif bump_type == "minor":
            minor += 1
            patch = 0
        else:  # patch
            patch += 1

        return f"{major}.{minor}.{patch}"
    except Exception:
        return current_version


if __name__ == "__main__":
    test_cases = [
        (["tools/_sku_mapper.py"], "修复了门店解析 bug", "patch"),
        (["SKILL.md", "README.md"], "更新文档", "patch"),
        (["tools/_order_parser.py", "tools/_store_matcher.py"], "新增支持PDF格式", "minor"),
        (["db/connection.py"], "优化了数据库连接逻辑", "minor"),
    ]

    for files, msg, expected in test_cases:
        result, reason = decide_version_bump(files, "", msg)
        status = "✅" if result == expected else "❌"
        print(f"{status} files={files}")
        print(f"   msg={msg} | {result} ({reason}) | expected={expected}")
#!/usr/bin/env python3
"""CHANGELOG 写入器 — 更新 VERSION 和 CHANGELOG.md"""
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Optional


def run_git(cwd: str, *args):
    """执行 git 命令"""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def get_current_version(skill_path: str) -> Optional[str]:
    """读取当前 VERSION"""
    vf = Path(skill_path) / "VERSION"
    if vf.exists():
        return vf.read_text().strip()
    return None


def update_version(skill_path: str, new_version: str):
    """更新 VERSION 文件"""
    vf = Path(skill_path) / "VERSION"
    vf.write_text(new_version.strip() + "\n")


def parse_changelog_tpl(bump_type: str, reason: str, changed_files: list, session: str = "") -> dict:
    """生成 CHANGELOG 条目"""
    section_map = {
        "major": "### Changed",
        "minor": "### Added",
        "patch": "### Fixed",
    }
    default_map = {
        "major": "功能变更（需 major 版本递增）",
        "minor": "新增功能或优化",
        "patch": "修复或微调",
    }
    section = section_map.get(bump_type, "### Changed")
    default_note = default_map.get(bump_type, "调整")

    # 从 changed_files 提取关键信息
    file_summary = []
    for f in changed_files[:10]:
        file_summary.append(f"  • `{f}`")
    files_text = "\n".join(file_summary)

    entry = {
        "version": None,  # 稍后填充
        "date": datetime.now().strftime("%Y-%m-%d"),
        "section": section,
        "body": f"- {reason}",
        "files": files_text,
        "session": session,
        "changed_files": changed_files,
        "bump_type": bump_type,
        "reason": reason,
    }
    return entry


def append_changelog(skill_path: str, entry: dict, current_version: str, new_version: str):
    """追加 CHANGELOG 条目到文件顶部"""
    changelog_path = Path(skill_path) / "CHANGELOG.md"
    entry["version"] = new_version

    section = entry["section"]
    body = entry["body"]
    files_text = entry["files"]
    session = entry["session"]
    date = entry["date"]

    files_block = f"\n\n**改动文件：**\n{files_text}" if files_text else ""
    session_block = f"\n**触发来源：** session `{session}`" if session else ""

    new_entry = f"""## [{new_version}] - {date}

{section}
{body}{files_block}{session_block}

"""

    if changelog_path.exists():
        existing = changelog_path.read_text()
        # 找到 ## [ 最新版本 ] 的位置，在它后面插入
        # 或者直接插在最顶部
        new_content = new_entry + existing
    else:
        new_content = new_entry + """# Changelog

<!-- guided by Keep a Changelog -->

"""

    changelog_path.write_text(new_content)


def commit_changes(skill_path: str, version: str, entry: dict) -> bool:
    """Git add + commit"""
    git_root = skill_path  # skill 本身是 git 仓库根

    # 判断是独立仓库还是共享仓库
    rel_path = ""
    parent = Path(skill_path)
    if not (parent / ".git").exists():
        return False

    # Add 所有变更
    run_git(skill_path, "add", "-A")

    # Check if anything staged
    out, _, rc = run_git(skill_path, "status", "--porcelain")
    if rc != 0 or not out.strip():
        return False

    # Commit
    changed_files_str = ", ".join(entry.get("changed_files", [])[:5])
    if len(entry.get("changed_files", [])) > 5:
        changed_files_str += f" (+{len(entry['changed_files']) - 5} more)"

    commit_msg = f"""{entry['bump_type'].capitalize()}: bump version to {version}

{entry['reason']}

Changed files: {changed_files_str}
Bump type: {entry['bump_type']}
"""

    out, err, rc = run_git(skill_path, "commit", "-m", commit_msg)
    if rc != 0:
        print(f"Git commit failed: {err}")
        return False

    return True


def auto_update_changelog(skill_path: str, new_version: str, bump_type: str, reason: str, changed_files: list, session: str = "") -> dict:
    """全自动：更新 VERSION + 写 CHANGELOG + commit"""
    # 1. 更新 VERSION
    update_version(skill_path, new_version)

    # 2. 生成 CHANGELOG 条目
    entry = parse_changelog_tpl(bump_type, reason, changed_files, session)

    # 3. 追加 CHANGELOG
    append_changelog(skill_path, entry, "", new_version)

    # 4. Git commit
    commit_ok = commit_changes(skill_path, new_version, entry)

    return {
        "version": new_version,
        "bump_type": bump_type,
        "reason": reason,
        "changed_files": changed_files,
        "commit_ok": commit_ok,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python changelog_writer.py <skill_path> <new_version>")
    else:
        skill_path = sys.argv[1]
        new_version = sys.argv[2]
        result = auto_update_changelog(skill_path, new_version, "minor", "测试更新", ["tools/test.py"], "om_test")
        print(result)
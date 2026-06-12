#!/usr/bin/env python3
"""Git 变更扫描器 — 扫描所有工作区的 Skill Git 变更"""
import subprocess
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

WORKSPACES_BASE = Path.home() / "openclaw-workspaces"


def run_git(cwd: str, *args) -> tuple[str, str, int]:
    """执行 git 命令，返回 (stdout, stderr, returncode)"""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as e:
        return "", str(e), 1


def get_git_root(skill_path: str) -> Optional[str]:
    """找最近的有 .git 的父目录"""
    path = Path(skill_path).resolve()
    while path != path.parent:
        if (path / ".git").exists():
            return str(path)
        path = path.parent
    return None


def get_last_commit_info(skill_path: str) -> Dict:
    """获取 Skill 最近一次 commit 的信息"""
    git_root = get_git_root(skill_path)
    if not git_root:
        return {"sha": None, "msg": None, "author": None, "time": None}

    # 相对于 git root 的路径
    rel = str(Path(skill_path).resolve()).replace(git_root, "").lstrip("/")

    out, _, rc = run_git(git_root, "log", "-1", f"--format=%H%n%an%n%ai%n%s", "--", rel or ".")
    if rc != 0 or not out:
        return {"sha": None, "msg": None, "author": None, "time": None}

    lines = out.split("\n")
    return {
        "sha": lines[0] if len(lines) > 0 else None,
        "author": lines[1] if len(lines) > 1 else None,
        "time": lines[2] if len(lines) > 2 else None,
        "msg": lines[3] if len(lines) > 3 else None,
    }


def get_changed_files(skill_path: str, since_commit: Optional[str] = None) -> List[str]:
    """获取自指定 commit 以来变更的文件列表"""
    git_root = get_git_root(skill_path)
    if not git_root:
        return []

    rel = str(Path(skill_path).resolve()).replace(git_root, "").lstrip("/")
    target = rel or "."

    if since_commit:
        out, _, rc = run_git(git_root, "diff", "--name-only", f"{since_commit}..HEAD", "--", target)
    else:
        out, _, rc = run_git(git_root, "diff", "--name-only", "HEAD", "--", target)

    if rc != 0:
        return []
    return [f for f in out.split("\n") if f.strip()]


def get_diff_content(skill_path: str, since_commit: Optional[str] = None) -> str:
    """获取变更的 diff 内容"""
    git_root = get_git_root(skill_path)
    if not git_root:
        return ""

    rel = str(Path(skill_path).resolve()).replace(git_root, "").lstrip("/")
    target = rel or "."

    if since_commit:
        out, _, rc = run_git(git_root, "diff", f"{since_commit}..HEAD", "--", target)
    else:
        out, _, rc = run_git(git_root, "diff", "HEAD", "--", target)

    return out if rc == 0 else ""


def scan_all_skills() -> List[Dict]:
    """扫描所有工作区，返回有变更的 Skill 列表"""
    results = []

    if not WORKSPACES_BASE.exists():
        return results

    for ws_dir in sorted(WORKSPACES_BASE.iterdir()):
        if not ws_dir.is_dir():
            continue
        if ws_dir.name.startswith("."):
            continue

        skills_dir = ws_dir / "skills"
        if not skills_dir.exists():
            continue

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name in ("docs", "backups"):
                continue

            # 检查是否有 SKILL.md
            if not (skill_dir / "SKILL.md").exists():
                continue

            # 检查是否是 git 仓库
            git_root = get_git_root(str(skill_dir))
            if not git_root:
                continue

            # 获取变更
            commit_info = get_last_commit_info(str(skill_dir))
            changed_files = get_changed_files(str(skill_dir))

            # 判断是否有未提交变更
            out, _, rc = run_git(git_root, "status", "--porcelain", "--", str(skill_dir.relative_to(Path(git_root))))
            has_uncommitted = rc == 0 and bool(out.strip())

            results.append({
                "workspace": ws_dir.name,
                "skill_name": skill_dir.name,
                "skill_path": str(skill_dir),
                "git_root": git_root,
                "last_commit": commit_info,
                "changed_files": changed_files,
                "has_uncommitted": has_uncommitted,
                "uncommitted_status": out if has_uncommitted else "",
            })

    return results


def get_skill_changes(skill_path: str) -> Dict:
    """获取单个 Skill 的详细变更信息"""
    git_root = get_git_root(skill_path)
    if not git_root:
        return {"error": "Not a git repository"}

    rel = str(Path(skill_path).resolve()).replace(git_root, "").lstrip("/")
    target = rel or "."

    # 未提交变更
    out, _, rc = run_git(git_root, "diff", "--name-only", "HEAD", "--", target)
    changed_files = out.split("\n") if rc == 0 else []

    out, _, rc = run_git(git_root, "diff", "HEAD", "--", target)
    diff_content = out if rc == 0 else ""

    # 已提交的最新 commit 信息
    commit_info = get_last_commit_info(skill_path)

    return {
        "skill_path": skill_path,
        "git_root": git_root,
        "changed_files": [f for f in changed_files if f.strip()],
        "diff_content": diff_content[:5000],  # 限制长度
        "last_commit": commit_info,
    }


def get_current_version(skill_path: str) -> Optional[str]:
    """读取 VERSION 文件"""
    vf = Path(skill_path) / "VERSION"
    if vf.exists():
        return vf.read_text().strip()
    return None


if __name__ == "__main__":
    skills = scan_all_skills()
    print(f"扫描了 {len(skills)} 个 Skills")
    for s in skills:
        print(f"\n[{s['workspace']}] {s['skill_name']}")
        print(f"  路径: {s['skill_path']}")
        print(f"  是否有未提交变更: {s['has_uncommitted']}")
        if s['last_commit']["sha"]:
            print(f"  最新: {s['last_commit']['sha'][:8]} | {s['last_commit']['msg']}")
        print(f"  改动文件: {s['changed_files']}")
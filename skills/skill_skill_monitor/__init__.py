#!/usr/bin/env python3
"""
skill-skill-monitor 入口
用法：
    from skill_skill_monitor import execute
    execute()
"""
import sys
from pathlib import Path

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent))

from tools.git_scanner import scan_all_skills, get_skill_changes, get_current_version
from tools.version_decider import decide_version_bump, bump_version
from tools.changelog_writer import auto_update_changelog
from tools.notifier import notify_change


def execute():
    """主入口：扫描所有 Skill，发现变更则自动更新版本"""
    print("=" * 50)
    print("🦎 Skill 版本监控器")
    print("=" * 50)

    # 1. 扫描
    skills = scan_all_skills()
    changed_skills = [s for s in skills if s["has_uncommitted"]]

    if not changed_skills:
        print(f"\n扫描了 {len(skills)} 个 Skills，无未提交变更")
        return {"status": "ok", "scanned": len(skills), "changed": 0}

    print(f"\n扫描了 {len(skills)} 个 Skills，发现 {len(changed_skills)} 个有未提交变更")

    results = []
    for skill in changed_skills:
        skill_name = skill["skill_name"]
        workspace = skill["workspace"]
        skill_path = skill["skill_path"]
        status = skill["uncommitted_status"]

        print(f"\n{'─' * 40}")
        print(f"📦 [{workspace}] {skill_name}")

        # 获取详细变更
        changes = get_skill_changes(skill_path)
        changed_files = changes.get("changed_files", [])
        diff_content = changes.get("diff_content", "")

        if not changed_files:
            print("  无变更文件，跳过")
            continue

        print(f"  改动文件: {', '.join(changed_files[:5])}")

        # 读取当前版本
        old_version = get_current_version(skill_path) or "0.0.0"
        print(f"  当前版本: {old_version}")

        # 判断版本变化级别
        bump_type, reason = decide_version_bump(changed_files, diff_content)
        print(f"  版本变化: {bump_type} — {reason}")

        # 递增版本号
        new_version = bump_version(old_version, bump_type)
        print(f"  新版本:   {old_version} → {new_version}")

        # 自动更新
        result = auto_update_changelog(
            skill_path=skill_path,
            new_version=new_version,
            bump_type=bump_type,
            reason=reason,
            changed_files=changed_files,
            session="auto-monitor",
        )
        print(f"  Git提交:  {'✅' if result['commit_ok'] else '❌'}")

        # 飞书通知
        try:
            notify_change(
                skill_name=skill_name,
                workspace=workspace,
                old_version=old_version,
                new_version=new_version,
                bump_type=bump_type,
                reason=reason,
                changed_files=changed_files,
                commit_ok=result["commit_ok"],
            )
        except Exception as e:
            print(f"  飞书通知失败: {e}")

        results.append({**result, "skill_name": skill_name, "workspace": workspace})

    print(f"\n{'=' * 50}")
    print(f"完成，共处理 {len(results)} 个 Skill")
    print("=" * 50)

    return {
        "status": "ok",
        "scanned": len(skills),
        "changed": len(changed_skills),
        "processed": len(results),
        "results": results,
    }


if __name__ == "__main__":
    execute()
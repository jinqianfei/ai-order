#!/usr/bin/env python3
"""
Memory closed-loop contract tests.

These tests avoid network and DB writes. They guard the local memory loop:
plan, indexes, startup checks, daily maintenance wiring, and version alignment.
"""
import json
import subprocess
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
PROJECT_DIR = WORKSPACE / "memory" / "projects" / "ai-order"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_memory_files_exist():
    required = [
        WORKSPACE / "memory" / "MEMORY_CLOSED_LOOP_UPGRADE_PLAN.md",
        PROJECT_DIR / "PROJECT.md",
        PROJECT_DIR / "problems" / "PENDING.md",
        PROJECT_DIR / "sessions" / "INDEX.md",
        PROJECT_DIR / "files" / "INDEX.md",
        PROJECT_DIR / "outputs" / "INDEX.md",
        PROJECT_DIR / "skills" / "INDEX.md",
        WORKSPACE / "memory" / "credentials" / "INDEX.md",
        WORKSPACE / "memory_system" / "protocols" / "SESSION_END_PROTOCOL.md",
    ]
    missing = [str(p.relative_to(WORKSPACE)) for p in required if not p.exists()]
    assert not missing, missing


def test_project_version_matches_skill_version():
    version = read(WORKSPACE / "skills" / "skill_order_to_huading_template" / "VERSION").strip()
    project = read(PROJECT_DIR / "PROJECT.md")
    skills_index = read(PROJECT_DIR / "skills" / "INDEX.md")
    assert version == "5.16.2"
    assert version in project
    assert version in skills_index


def test_session_end_protocol_requires_maintenance():
    protocol = read(WORKSPACE / "memory_system" / "protocols" / "SESSION_END_PROTOCOL.md")
    for needle in [
        "sessions/INDEX.md",
        "files/INDEX.md",
        "outputs/INDEX.md",
        "skills/INDEX.md",
        "extract_memory.py --apply --days 14",
        "check_quality.py",
        "reindex.py",
        "startup_check.py",
    ]:
        assert needle in protocol, needle


def test_daily_wrap_runs_memory_maintenance():
    daily = read(WORKSPACE / "ops" / "daily_wrap.sh")
    for needle in [
        "Step 4.5: 记忆闭环维护",
        "memory_system/scripts/startup_check.py",
        "memory_system/scripts/extract_memory.py --apply --days 14",
        "memory_system/scripts/check_quality.py",
        "memory_system/scripts/reindex.py",
        "记忆闭环维护结果已追加到日结报告",
    ]:
        assert needle in daily, needle


def test_startup_check_json_contract():
    result = subprocess.run(
        [sys.executable, "memory_system/scripts/startup_check.py", "--json"],
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode in (0, 1), result.stderr + result.stdout
    data = json.loads(result.stdout)
    names = {item["name"] for item in data["checks"]}
    expected = {
        "memory_fresh",
        "no_pending",
        "project_version",
        "project_indexes",
        "credentials_index",
        "memory_index",
    }
    assert expected.issubset(names), names
    assert not any(item["level"] == "fail" for item in data["checks"]), data["checks"]


def main():
    tests = [
        test_required_memory_files_exist,
        test_project_version_matches_skill_version,
        test_session_end_protocol_requires_maintenance,
        test_daily_wrap_runs_memory_maintenance,
        test_startup_check_json_contract,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print("PASSED memory closed-loop contract tests")


if __name__ == "__main__":
    main()

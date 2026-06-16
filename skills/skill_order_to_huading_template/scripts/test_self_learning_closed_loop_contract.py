#!/usr/bin/env python3
"""
Self-learning closed-loop contract tests.

These checks intentionally avoid DB writes. They guard the interfaces that
daily_wrap.sh and learning.improver rely on to keep the closed loop connected.
"""
import os
import sys
import tempfile

import yaml


WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SKILL_DIR = os.path.join(WORKSPACE, "skills", "skill_order_to_huading_template")
for path in (WORKSPACE, SKILL_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def test_version_contract():
    from __init__ import OrderToHuadingTemplate

    with open(os.path.join(SKILL_DIR, "VERSION"), "r", encoding="utf-8") as f:
        version_file = f.read().strip()
    assert OrderToHuadingTemplate.VERSION == version_file, (
        OrderToHuadingTemplate.VERSION,
        version_file,
    )


def test_improver_import_contract():
    from learning import improver

    assert improver._SKILL_ROOT in sys.path
    assert improver.get_default_db_config is not None
    assert improver.psycopg2 is not None


def test_keyword_apply_reaches_active_product_types():
    from learning import improver

    old_path = improver.KEYWORDS_CONFIG_YAML
    try:
        with tempfile.TemporaryDirectory() as tmp:
            test_yaml = os.path.join(tmp, "keywords_config.yaml")
            with open(test_yaml, "w", encoding="utf-8") as f:
                yaml.safe_dump({
                    "product_types": ["鸡排"],
                    "flavor_types": ["酱料"],
                }, f, allow_unicode=True)

            improver.KEYWORDS_CONFIG_YAML = test_yaml
            added = improver.apply_keyword_changes([
                {"keyword": "牛肉饼", "count": 5, "sample_names": ["牛肉饼新品"]}
            ])
            assert added == 1

            with open(test_yaml, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            assert "牛肉饼" in data.get("product_types", [])
            assert any(k.get("keyword") == "牛肉饼" for k in data.get("auto_keywords", []))
    finally:
        improver.KEYWORDS_CONFIG_YAML = old_path


def test_order_complete_user_modified_contract():
    init_path = os.path.join(SKILL_DIR, "__init__.py")
    with open(init_path, "r", encoding="utf-8") as f:
        source = f.read()
    assert '"user_modified": _sku_user_modified' in source
    assert 'VERSION = "5.16.3"' in source


def test_json_entrypoint_contracts():
    from importlib import import_module

    history_replay = import_module("scripts.history_replay")
    accuracy_comparison = import_module("scripts.accuracy_comparison")

    # argparse should know these flags; SystemExit(0) is the expected --help path.
    for module in (history_replay, accuracy_comparison):
        try:
            module.main(["--help"])
        except SystemExit as exc:
            assert exc.code == 0


def main():
    tests = [
        test_version_contract,
        test_improver_import_contract,
        test_keyword_apply_reaches_active_product_types,
        test_order_complete_user_modified_contract,
        test_json_entrypoint_contracts,
    ]
    for test in tests:
        test()
        print(f"✅ {test.__name__}")
    print("PASSED self-learning closed-loop contract tests")


if __name__ == "__main__":
    main()

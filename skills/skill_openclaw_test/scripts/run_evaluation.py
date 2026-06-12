#!/usr/bin/env python3
"""
OpenClaw Skill 测评脚本
用法:
    python scripts/run_evaluation.py \
        --skill-path ../skill_order_to_huading_template \
        --db-config ../config/db_config.yaml \
        --test-data ../test_data \
        --output ../docs/测评报告.md
"""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加 skill 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from skill_openclaw_test import SkillTester


def main():
    parser = argparse.ArgumentParser(description="OpenClaw Skill 测评")
    parser.add_argument("--skill-path", required=True, help="Skill 代码路径")
    parser.add_argument("--db-config", required=True, help="数据库配置文件")
    parser.add_argument("--test-data", required=True, help="测试数据目录")
    parser.add_argument("--old-version", default="v5.4", help="旧版本号")
    parser.add_argument("--new-version", default="v5.5", help="新版本号")
    parser.add_argument("--test-sets", default="A", help="测试集，如 ABCD")
    parser.add_argument("--output", default="测评报告.md", help="输出报告路径")
    args = parser.parse_args()

    # 加载 db_config
    db_cfg = {
        "host": "localhost", "port": 5432,
        "database": "neo", "user": "jinqianfei"
    }

    # 执行测评
    tester = SkillTester(db_config=db_cfg, test_data_dir=args.test_data)
    result = tester.evaluate(
        skill_path=args.skill_path,
        test_sets=list(args.test_sets),
        old_version=args.old_version,
        new_version=args.new_version,
    )

    # 生成 Markdown 报告
    report_md = tester.generate_markdown_report(
        result, args.old_version, args.new_version
    )

    # 保存报告
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report_md)

    print(f"测评完成！报告已保存到: {output_path}")
    print(f"准确率: {result['accuracy']}")
    print(f"测试总数: {result['total_tests']}")


if __name__ == "__main__":
    main()
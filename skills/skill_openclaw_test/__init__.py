"""
skill-openclaw-test - OpenClaw Skill 通用测评框架

用法:
    from skill_openclaw_test import SkillTester

    tester = SkillTester(db_config={
        "host": "localhost", "port": 5432,
        "database": "neo", "user": "jinqianfei"
    })

    result = tester.evaluate(
        skill_path="skills/skill_order_to_huading_template/",
        test_data_dir="docs/test_data/"
    )
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict

__version__ = "1.0"


@dataclass
class GroundTruthItem:
    """单个商品的 Ground Truth"""
    seq: int
    product_name: str
    spec: str = ""
    quantity: float = 0
    unit: str = "件"
    ground_truth_sku_code: str = ""
    ground_truth_sku_name: str = ""
    ground_truth_unit: str = ""
    ground_truth_unit_type: str = ""


@dataclass
class GroundTruthStore:
    """单个门店的 Ground Truth"""
    store_name: str
    ground_truth_store_code: str = ""
    ground_truth_owner_code: str = ""
    ground_truth_warehouse_code: str = ""
    items: List[GroundTruthItem] = None


@dataclass
class TestSample:
    """单个测试样本"""
    test_id: str
    order_file: str
    order_format: str  # huading_standard / xiaojiangxi / tianjin / huading_output
    stores: List[GroundTruthStore] = None


@dataclass
class EvaluationResult:
    """单个商品的评估结果"""
    test_id: str
    store_name: str
    product_name: str
    old_confidence: float = 0.0
    new_confidence: float = 0.0
    matched_sku_code: str = ""
    ground_truth_sku_code: str = ""
    match_status: str = "unknown"  # hit / miss / low_confidence / regression
    match_method: str = ""
    improvement: float = 0.0
    reason: str = ""


class SkillTester:
    """Skill 测评框架"""

    def __init__(self, db_config: dict, test_data_dir: str = "test_data/"):
        self.db_config = db_config
        self.test_data_dir = Path(test_data_dir)

    def load_test_samples(self, test_set: str = "A") -> List[TestSample]:
        """加载测试数据集"""
        path = self.test_data_dir / f"test_set_{test_set}.json"
        if not path.exists():
            return []
        with open(path) as f:
            data = json.load(f)
        return [self._parse_sample(s) for s in data]

    def _parse_sample(self, data: dict) -> TestSample:
        stores = []
        for s in data.get("stores", []):
            items = [
                GroundTruthItem(
                    seq=i["seq"],
                    product_name=i["product_name"],
                    spec=i.get("spec", ""),
                    quantity=i.get("quantity", 0),
                    unit=i.get("unit", "件"),
                    ground_truth_sku_code=i.get("ground_truth_sku_code", ""),
                    ground_truth_sku_name=i.get("ground_truth_sku_name", ""),
                    ground_truth_unit=i.get("ground_truth_unit", ""),
                    ground_truth_unit_type=i.get("ground_truth_unit_type", ""),
                )
                for i in s.get("items", [])
            ]
            stores.append(GroundTruthStore(
                store_name=s["store_name"],
                ground_truth_store_code=s.get("ground_truth_store_code", ""),
                ground_truth_owner_code=s.get("ground_truth_owner_code", ""),
                ground_truth_warehouse_code=s.get("ground_truth_warehouse_code", ""),
                items=items,
            ))
        return TestSample(
            test_id=data["test_id"],
            order_file=data["order_file"],
            order_format=data.get("order_format", "unknown"),
            stores=stores,
        )

    def evaluate(
        self,
        skill_path: str,
        test_sets: List[str] = None,
        old_version: str = None,
        new_version: str = None,
    ) -> Dict[str, Any]:
        """
        执行测评

        Args:
            skill_path: Skill 代码路径
            test_sets: 测试集列表，如 ["A", "B", "C"]
            old_version: 旧版本号（用于对比）
            new_version: 新版本号（当前版本）
        """
        test_sets = test_sets or ["A"]
        all_samples = []
        for ts in test_sets:
            all_samples.extend(self.load_test_samples(ts))

        results = []
        for sample in all_samples:
            for store in sample.stores:
                for item in store.items:
                    result = self._evaluate_item(
                        sample.test_id, store, item, skill_path
                    )
                    results.append(asdict(result))

        return self._build_report(results, old_version, new_version)

    def _evaluate_item(
        self, test_id: str, store: GroundTruthStore, item: GroundTruthItem,
        skill_path: str
    ) -> EvaluationResult:
        """评估单个商品"""
        # 导入 sku_mapper
        import sys
        sys.path.insert(0, skill_path)
        from tools.sku_mapper import map_sku

        owner_code = store.ground_truth_owner_code
        if not owner_code:
            return EvaluationResult(
                test_id=test_id, store_name=store.store_name,
                product_name=item.product_name,
                match_status="skip", reason="无货主ID"
            )

        sku_result = map_sku(owner_code, item.product_name, item.unit, self.db_config)

        confidence = sku_result.get("confidence", 0.0)
        matched_code = sku_result.get("sku_code", "")
        gt_code = item.ground_truth_sku_code

        if not matched_code:
            status = "miss"
        elif matched_code == gt_code:
            status = "hit"
        else:
            status = "wrong_sku"

        if status == "hit" and confidence < 0.8:
            status = "low_confidence"

        return EvaluationResult(
            test_id=test_id,
            store_name=store.store_name,
            product_name=item.product_name,
            new_confidence=confidence,
            matched_sku_code=matched_code,
            ground_truth_sku_code=gt_code,
            match_status=status,
            match_method=sku_result.get("match_method", ""),
        )

    def _build_report(
        self, results: List[dict], old_version: str, new_version: str
    ) -> Dict[str, Any]:
        """构建测评报告"""
        total = len(results)
        hit = sum(1 for r in results if r["match_status"] == "hit")
        miss = sum(1 for r in results if r["match_status"] == "miss")
        low_conf = sum(1 for r in results if r["match_status"] == "low_confidence")
        wrong = sum(1 for r in results if r["match_status"] == "wrong_sku")

        high_conf = sum(1 for r in results if r["new_confidence"] >= 0.8)
        medium_conf = sum(1 for r in results if 0.7 <= r["new_confidence"] < 0.8)
        low_conf_only = sum(1 for r in results if r["new_confidence"] < 0.7)

        improved = [r for r in results if r["improvement"] > 0]
        regressions = [r for r in results if r["improvement"] < -0.05]

        high_ratio = f"{high_conf/total*100:.1f}%" if total > 0 else "0%"
        medium_ratio = f"{medium_conf/total*100:.1f}%" if total > 0 else "0%"
        low_ratio = f"{low_conf_only/total*100:.1f}%" if total > 0 else "0%"
        accuracy = f"{hit/total*100:.1f}%" if total > 0 else "0%"
        
        return {
            "evaluation_date": datetime.now().strftime("%Y-%m-%d"),
            "skill_version": new_version,
            "total_tests": total,
            "matched": hit,
            "unmatched": miss,
            "accuracy": accuracy,
            "confidence_distribution": {
                "high_≥0.8": {"count": high_conf, "ratio": high_ratio},
                "medium_0.7-0.8": {"count": medium_conf, "ratio": medium_ratio},
                "low_<0.7": {"count": low_conf_only, "ratio": low_ratio},
            },
            "match_status_breakdown": {
                "correct_sku": hit,
                "wrong_sku": wrong,
                "low_confidence": low_conf,
                "not_matched": miss,
            },
            "improved_items": improved,
            "regressed_items": regressions,
            "unmatched_items": [r for r in results if r["match_status"] in ("miss", "low_confidence")],
        }

    def generate_markdown_report(self, report: dict, old_version: str, new_version: str) -> str:
        """生成 Markdown 测评报告"""
        lines = [
            f"# Skill {new_version} 测评报告（{old_version or '基准'} → {new_version}）",
            "",
            f"**测评日期**: {report['evaluation_date']}",
            f"**测试总数**: {report['total_tests']}",
            "",
            "## 整体准确率",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 准确率 | **{report['accuracy']}** |",
            f"| 高置信度(≥0.8) | {report['confidence_distribution']['high_≥0.8']['count']} ({report['confidence_distribution']['high_≥0.8']['ratio']}) |",
            f"| 中置信度(0.7-0.8) | {report['confidence_distribution']['medium_0.7-0.8']['count']} ({report['confidence_distribution']['medium_0.7-0.8']['ratio']}) |",
            f"| 低置信度(<0.7) | {report['confidence_distribution']['low_<0.7']['count']} ({report['confidence_distribution']['low_<0.7']['ratio']}) |",
            "",
        ]

        if report.get("improved_items"):
            lines += ["## 改善商品", "", "| 商品名称 | 门店 | 旧置信度 | 新置信度 | 改善 |", "|----------|------|---------|---------|------|"]
            for r in report["improved_items"][:20]:
                lines.append(f"| {r['product_name']} | {r['store_name']} | {r.get('old_confidence', '-')} | **{r['new_confidence']}** | {r.get('improvement', 0):+.2f} |")

        if report.get("unmatched_items"):
            lines += ["\n## 未匹配/低置信度商品", "", "| 商品名称 | 门店 | 置信度 | 原因 |", "|----------|------|---------|------|"]
            for r in report["unmatched_items"][:20]:
                lines.append(f"| {r['product_name']} | {r['store_name']} | {r['new_confidence']} | {r.get('reason', '-')} |")

        return "\n".join(lines)
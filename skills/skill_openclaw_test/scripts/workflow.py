#!/usr/bin/env python3
"""
自动化测评与修复工作流脚本

用法:
    python scripts/workflow.py \
        --skill-path ../skill_order_to_huading_template \
        --action evaluate_and_repair \
        --db-config ../config/db_config.yaml \
        --ec2-host 13.212.17.85

流程:
    测评 → 报告 → 风险分级 → 确认/修复 → 复测 → 部署
"""

import argparse
import subprocess
import sys
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 动态添加路径，使 skill_openclaw_test 及父目录可导入
_workspace_root = Path(__file__).parent.parent.parent.resolve()  # ai-order/
_skill_root = Path(__file__).parent.parent.resolve()  # skills/skill_openclaw_test/
_skills_dir = _skill_root.parent.resolve()  # skills/

for p in [str(_workspace_root), str(_skills_dir), str(_skill_root)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from skill_openclaw_test import SkillTester
from skill_openclaw_test.scripts.auto_repair import AutoRepairSkill, GitBackupManager


class WorkflowOrchestrator:
    """工作流编排器"""
    
    def __init__(
        self,
        skill_path: str,
        db_config: dict,
        ec2_host: str = "13.212.17.85",
        ec2_user: str = "ec2-user",
        ec2_key: str = "~/.ssh/openclaw-ec2.pem",
        workspace_dir: str = None,
    ):
        self.skill_path = Path(skill_path)
        self.db_config = db_config
        self.ec2_host = ec2_host
        self.ec2_user = ec2_user
        self.ec2_key = os.path.expanduser(ec2_key)
        self.workspace_dir = workspace_dir or str(self.skill_path.parent)
        
        self.workspace_name = self.skill_path.name
        self.report_path = self.skill_path.parent / "docs" / f"测评报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        # 结果记录
        self.results = {
            "workflow_started": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "skill_path": str(self.skill_path),
            "steps": [],
            "final_status": "pending",
        }
    
    # ============================================================
    # 步骤1: 自动化测评
    # ============================================================
    def step1_evaluate(self) -> Dict[str, Any]:
        """执行自动化测评"""
        step_result = {"step": "step1_evaluate", "status": "running", "started_at": datetime.now().strftime("%H:%M:%S")}
        
        print("\n" + "=" * 60)
        print(">>> Step 1: 自动化测评")
        print("=" * 60)
        
        try:
            # 尝试加载测试数据
            test_sets = []
            test_data_dir = Path(__file__).parent.parent / "test_data"
            if not test_data_dir.exists():
                test_data_dir = self.skill_path.parent / "skills" / "skill_openclaw_test" / "test_data"
            if test_data_dir.exists():
                for f in test_data_dir.glob("test_set_*.json"):
                    test_sets.append(f.stem.replace("test_set_", ""))
            
            print(f"  测试集: {test_sets or ['A (default)']}")
            print(f"  测试数据目录: {test_data_dir}")
            
            tester = SkillTester(
                db_config=self.db_config,
                test_data_dir=str(test_data_dir.resolve())
            )
            
            result = tester.evaluate(
                skill_path=str(self.skill_path),
                test_sets=test_sets if test_sets else ["A"],
                old_version="baseline",
                new_version="current",
            )
            
            # 生成报告
            report_md = tester.generate_markdown_report(result, "baseline", "current")
            
            # 保存报告
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.report_path, "w") as f:
                f.write(report_md)
            
            accuracy = result.get("accuracy", "N/A")
            total = result.get("total_tests", 0)
            hit = result.get("matched", 0)
            miss = result.get("unmatched", 0)
            low_conf = result.get("match_status_breakdown", {}).get("low_confidence", 0)
            
            step_result.update({
                "status": "success",
                "completed_at": datetime.now().strftime("%H:%M:%S"),
                "report_path": str(self.report_path),
                "accuracy": accuracy,
                "total_tests": total,
                "unmatched_count": miss,
                "items_matched": hit,
                "items_low_conf": low_conf,
            })
            
            print(f"  ✅ 测评完成")
            print(f"  准确率: {accuracy}")
            print(f"  测试数: {total}")
            print(f"  匹配成功: {hit}")
            print(f"  未匹配: {miss}")
            print(f"  低置信: {low_conf}")
            print(f"  报告: {self.report_path}")
        
        except Exception as e:
            step_result.update({
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.now().strftime("%H:%M:%S"),
            })
            print(f"  ❌ 测评失败: {e}")
        
        self.results["steps"].append(step_result)
        return step_result
    
    # ============================================================
    # 步骤2: 风险分级判断
    # ============================================================
    def step2_risk_classify(self) -> Dict[str, Any]:
        """检查代码改动并做风险分级"""
        step_result = {"step": "step2_risk_classify", "status": "running", "started_at": datetime.now().strftime("%H:%M:%S")}
        
        print("\n" + "=" * 60)
        print(">>> Step 2: 风险分级判断")
        print("=" * 60)
        
        try:
            repair = AutoRepairSkill(str(self.skill_path))
            diffs = repair.check_skill_diff()
            
            # 分类汇总
            high_risk = [d for d in diffs if d.get("risk_level") in ("high_critical", "high")]
            ordinary = [d for d in diffs if d.get("can_auto_fix")]
            total_changed = len(diffs)
            
            step_result.update({
                "status": "success",
                "completed_at": datetime.now().strftime("%H:%M:%S"),
                "total_changed_files": total_changed,
                "high_risk_count": len(high_risk),
                "auto_fixable_count": len(ordinary),
                "requires_manual_confirmation": len(high_risk) > 0,
                "high_risk_files": [d["file"] for d in high_risk],
                "auto_fixable_files": [d["file"] for d in ordinary],
            })
            
            print(f"  改动文件: {total_changed} 个")
            print(f"  高风险: {len(high_risk)} 个 {'⚠️ 需人工确认' if high_risk else '✅ 无'}")
            print(f"  可自动修复: {len(ordinary)} 个 {'✅' if ordinary else '无'}")
            
            for d in diffs:
                risk_icon = "🔴" if d.get("risk_level") in ("high_critical", "high") else "🟡"
                auto_icon = "✅" if d.get("can_auto_fix") else "⏭️"
                print(f"  {risk_icon} {auto_icon} {d['file']} ({d.get('risk_level')})")
                for reason in d.get("reasons", [])[:2]:
                    print(f"      → {reason}")
        
        except Exception as e:
            step_result.update({"status": "failed", "error": str(e)})
            print(f"  ❌ 风险分级失败: {e}")
        
        self.results["steps"].append(step_result)
        return step_result
    
    # ============================================================
    # 步骤3: 确认/修复（根据风险分级）
    # ============================================================
    def step3_confirm_or_repair(self, auto_confirm: bool = False) -> Dict[str, Any]:
        """
        高风险 → 暂停等待人工确认
        普通风险 → 自动执行修复
        """
        step_result = {"step": "step3_confirm_or_repair", "status": "running", "started_at": datetime.now().strftime("%H:%M:%S")}
        
        print("\n" + "=" * 60)
        print(">>> Step 3: 确认/修复")
        print("=" * 60)
        
        # 获取上一步结果
        risk_result = self.results["steps"][-1] if self.results["steps"] else {}
        requires_manual = risk_result.get("requires_manual_confirmation", False)
        
        if requires_manual and not auto_confirm:
            # 高风险路径：暂停
            step_result.update({
                "status": "paused_manual_confirm",
                "completed_at": datetime.now().strftime("%H:%M:%S"),
                "message": "高风险改动，需要人工确认后继续",
                "high_risk_files": risk_result.get("high_risk_files", []),
            })
            print("  ⏸️ 高风险改动，流程暂停")
            print("  请人工审查以下文件后，确认是否继续：")
            for f in risk_result.get("high_risk_files", []):
                print(f"    🔴 {f}")
            print("\n  确认后，请重新运行并设置 --auto-confirm 参数")
        else:
            # 自动修复路径
            try:
                repair = AutoRepairSkill(str(self.skill_path))
                
                # 分析报告
                issues = []
                if self.report_path.exists():
                    report_data = repair.analyze_report(str(self.report_path))
                    issues = report_data.get("issues", [])
                
                # 检查代码改动
                diffs = repair.check_skill_diff()
                auto_fixable = [d for d in diffs if d.get("can_auto_fix")]
                
                if not auto_fixable and not issues:
                    step_result.update({
                        "status": "success",
                        "completed_at": datetime.now().strftime("%H:%M:%S"),
                        "message": "无需修复（无改动或无问题）",
                    })
                    print("  ✅ 无需修复")
                else:
                    # 生成并执行修复计划
                    fix_plan = repair.generate_fix_plan(issues, diffs)
                    fix_result = repair.execute_repair(fix_plan, action="execute")
                    
                    step_result.update({
                        "status": "success",
                        "completed_at": datetime.now().strftime("%H:%M:%S"),
                        "fixes_attempted": fix_result.get("fixes_attempted", 0),
                        "fixes_succeeded": fix_result.get("fixes_succeeded", 0),
                        "backup_branch": fix_result.get("backup_branch", "N/A"),
                        "message": fix_result.get("message", ""),
                    })
                    
                    print(f"  ✅ 修复执行完成")
                    print(f"  尝试: {fix_result.get('fixes_attempted', 0)} 项")
                    print(f"  成功: {fix_result.get('fixes_succeeded', 0)} 项")
                    if fix_result.get("backup_branch"):
                        print(f"  备份分支: {fix_result['backup_branch']}")
            
            except Exception as e:
                step_result.update({"status": "failed", "error": str(e)})
                print(f"  ❌ 修复失败: {e}")
        
        self.results["steps"].append(step_result)
        return step_result
    
    # ============================================================
    # 步骤4: 复测验证
    # ============================================================
    def step4_retest(self) -> Dict[str, Any]:
        """修复后复测，对比前后结果"""
        step_result = {"step": "step4_retest", "status": "running", "started_at": datetime.now().strftime("%H:%M:%S")}
        
        print("\n" + "=" * 60)
        print(">>> Step 4: 复测验证")
        print("=" * 60)
        
        try:
            # 获取修复前报告
            old_report = self.report_path
            if not old_report.exists():
                step_result.update({
                    "status": "skipped",
                    "message": "无修复前报告，跳过复测对比",
                })
                print("  ⏭️ 无修复前报告，跳过")
                return step_result
            
            # 重新测评
            test_data_dir = Path(__file__).parent.parent / "test_data"
            if not test_data_dir.exists():
                test_data_dir = self.skill_path.parent / "skills" / "skill_openclaw_test" / "test_data"
            
            test_sets = []
            if test_data_dir.exists():
                for f in test_data_dir.glob("test_set_*.json"):
                    test_sets.append(f.stem.replace("test_set_", ""))
            
            tester = SkillTester(
                db_config=self.db_config,
                test_data_dir=str(test_data_dir.resolve())
            )
            
            new_result = tester.evaluate(
                skill_path=str(self.skill_path),
                test_sets=test_sets if test_sets else ["A"],
                old_version="before_fix",
                new_version="after_fix",
            )
            
            # 生成新报告
            new_report_path = self.report_path.parent / f"复测报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            new_report_md = tester.generate_markdown_report(new_result, "修复前", "修复后")
            with open(new_report_path, "w") as f:
                f.write(new_report_md)
            
            step_result.update({
                "status": "success",
                "completed_at": datetime.now().strftime("%H:%M:%S"),
                "new_accuracy": new_result.get("accuracy"),
                "new_total": new_result.get("total_tests", 0),
                "new_unmatched": new_result.get("unmatched", 0),
                "new_report_path": str(new_report_path),
            })
            
            print(f"  ✅ 复测完成")
            print(f"  准确率: {new_result.get('accuracy')}")
            print(f"  未匹配: {new_result.get('unmatched', 0)}")
            print(f"  新报告: {new_report_path}")
            
            # 对比
            self.results["retest_result"] = step_result
        
        except Exception as e:
            step_result.update({"status": "failed", "error": str(e)})
            print(f"  ❌ 复测失败: {e}")
        
        self.results["steps"].append(step_result)
        return step_result
    
    # ============================================================
    # 步骤5: EC2部署
    # ============================================================
    def step5_deploy(self, force: bool = False) -> Dict[str, Any]:
        """同步到EC2并部署"""
        step_result = {"step": "step5_deploy", "status": "running", "started_at": datetime.now().strftime("%H:%M:%S")}
        
        print("\n" + "=" * 60)
        print(">>> Step 5: EC2 部署")
        print("=" * 60)
        
        # 检查复测结果
        retest = self.results.get("retest_result", {})
        if retest.get("status") == "failed" and not force:
            step_result.update({
                "status": "skipped",
                "message": "复测未通过，跳过部署",
            })
            print("  ⏭️ 复测未通过，跳过部署")
            return step_result
        
        try:
            # SSH连接检查
            ssh_check = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-i", self.ec2_key,
                 f"{self.ec2_user}@{self.ec2_host}", "echo 'EC2 connected'"],
                capture_output=True, text=True, timeout=15
            )
            
            if ssh_check.returncode != 0:
                raise Exception(f"EC2连接失败: {ssh_check.stderr}")
            
            # 同步文件（只同步 skill_openclaw_test 目录）
            sync_cmd = [
                "rsync", "-avz",
                "-e", f"ssh -o StrictHostKeyChecking=no -i {self.ec2_key}",
                str(self.skill_path.parent / "skills" / "skill_openclaw_test") + "/",
                f"{self.ec2_user}@{self.ec2_host}:/home/{self.ec2_user}/ai-order/skills/skill_openclaw_test/"
            ]
            
            sync_result = subprocess.run(
                sync_cmd,
                capture_output=True, text=True, timeout=60
            )
            
            if sync_result.returncode != 0:
                raise Exception(f"同步失败: {sync_result.stderr}")
            
            step_result.update({
                "status": "success",
                "completed_at": datetime.now().strftime("%H:%M:%S"),
                "ec2_host": self.ec2_host,
                "message": f"已同步到 {self.ec2_host}",
            })
            
            print(f"  ✅ 已同步到 {self.ec2_host}")
            print(f"  同步目录: skills/skill_openclaw_test/")
        
        except Exception as e:
            step_result.update({
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.now().strftime("%H:%M:%S"),
            })
            print(f"  ❌ 部署失败: {e}")
        
        self.results["steps"].append(step_result)
        return step_result
    
    # ============================================================
    # 完整工作流执行
    # ============================================================
    def run_full_workflow(
        self,
        auto_confirm: bool = False,
        skip_deploy: bool = False,
        force_deploy: bool = False,
    ) -> Dict[str, Any]:
        """执行完整工作流"""
        print("\n" + "=" * 70)
        print("  Skill 自动化测评与修复工作流")
        print(f"  Skill: {self.skill_path.name}")
        print(f"  开始时间: {self.results['workflow_started']}")
        print("=" * 70)
        
        # Step 1: 测评
        eval_result = self.step1_evaluate()
        
        # Step 2: 风险分级
        risk_result = self.step2_risk_classify()
        
        # Step 3: 确认/修复
        repair_result = self.step3_confirm_or_repair(auto_confirm=auto_confirm)
        
        if repair_result.get("status") == "paused_manual_confirm":
            self.results["final_status"] = "paused_manual_confirm"
            return self.results
        
        # Step 4: 复测
        retest_result = self.step4_retest()
        
        # Step 5: 部署
        if not skip_deploy:
            deploy_result = self.step5_deploy(force=force_deploy)
        else:
            deploy_result = {"status": "skipped", "message": "跳过部署"}
        
        # 最终状态
        failed_steps = [s for s in self.results["steps"] if s.get("status") == "failed"]
        if failed_steps:
            self.results["final_status"] = "failed"
        else:
            self.results["final_status"] = "success"
        
        self.results["workflow_completed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 汇总输出
        print("\n" + "=" * 70)
        print("  工作流执行完成")
        print(f"  最终状态: {self.results['final_status']}")
        print(f"  完成时间: {self.results.get('workflow_completed', 'N/A')}")
        print("=" * 70)
        
        # 汇总各步骤结果
        for s in self.results["steps"]:
            status_icon = {
                "success": "✅",
                "failed": "❌",
                "paused_manual_confirm": "⏸️",
                "skipped": "⏭️",
            }.get(s.get("status", ""), "⬜")
            print(f"  {status_icon} {s.get('step')}: {s.get('status')} — {s.get('message', '')}")
        
        return self.results


def main():
    parser = argparse.ArgumentParser(description="Skill 自动化测评与修复工作流")
    parser.add_argument("--skill-path", required=True, help="Skill 代码路径")
    parser.add_argument("--db-config", help="数据库配置文件路径")
    parser.add_argument("--ec2-host", default="13.212.17.85", help="EC2 主机地址")
    parser.add_argument("--ec2-user", default="ec2-user", help="EC2 用户名")
    parser.add_argument("--action", default="evaluate_and_repair",
                       choices=["evaluate_and_repair", "evaluate_only", "repair_only"],
                       help="工作流动作")
    parser.add_argument("--auto-confirm", action="store_true",
                       help="自动确认高风险（跳过人工确认）")
    parser.add_argument("--skip-deploy", action="store_true",
                       help="跳过部署步骤")
    parser.add_argument("--force-deploy", action="store_true",
                       help="强制部署（即使复测失败）")
    
    args = parser.parse_args()
    
    # 加载 db_config
    if args.db_config and os.path.exists(args.db_config):
        import yaml
        with open(args.db_config) as f:
            cfg = yaml.safe_load(f)
            db_config = cfg.get("db", {})
    else:
        db_config = {
            "host": "localhost",
            "port": 5432,
            "database": "neo",
            "user": "jinqianfei",
        }
    
    orchestrator = WorkflowOrchestrator(
        skill_path=args.skill_path,
        db_config=db_config,
        ec2_host=args.ec2_host,
        ec2_user=args.ec2_user,
    )
    
    if args.action == "evaluate_and_repair":
        orchestrator.run_full_workflow(
            auto_confirm=args.auto_confirm,
            skip_deploy=args.skip_deploy,
            force_deploy=args.force_deploy,
        )
    elif args.action == "evaluate_only":
        orchestrator.step1_evaluate()
        orchestrator.step2_risk_classify()
    elif args.action == "repair_only":
        orchestrator.step3_confirm_or_repair(auto_confirm=args.auto_confirm)


if __name__ == "__main__":
    main()
# Git 分支管理策略 — Skill 自动化测评与修复

## 背景

本策略用于规范 Skill 代码的修改、测评、修复流程，确保每次修改可追溯、可回滚、可合并。

---

## 分支命名规范

| 分支类型 | 命名格式 | 说明 |
|---------|---------|------|
| 主分支 | `main` | 稳定版本，始终可部署 |
| 开发分支 | `develop` | 下一版本开发中（可选） |
| 修复分支 | `fix/{date}-{type}` | 每次修复创建，如 `fix/20260604-sku_field` |
| 测评分支 | `test/{date}-{name}` | 测评专用，如 `test/20260604-regression` |
| 发布分支 | `release/{version}` | 发布前冻结，如 `release/v5.8.1` |

---

## 工作流分支策略

### 方式1：修复分支工作流（推荐）

```
main ──────────────────────────────────────────→ main
          │
          ├─ fix/20260604-sku_field  → 测评通过 → 合并回 main
          │       │
          │       └─ 修复改动 → auto_repair 执行
          │
          └─ fix/20260605-alias_update → 测评通过 → 合并回 main
```

**操作流程：**

```bash
# 1. 每次修复前，从 main 创建修复分支
git checkout main
git pull origin main
git checkout -b fix/20260604-sku-field

# 2. 在修复分支上执行改动（手动或自动修复）
# ... 修改代码 ...

# 3. 推送修复分支
git push origin fix/20260604-sku-field

# 4. 触发测评工作流（CI/CD 或手动）
python scripts/workflow.py \
  --skill-path skills/skill_order_to_huading_template \
  --action evaluate_and_repair

# 5. 测评通过后，合并回 main
git checkout main
git merge fix/20260604-sku-field --squash
git commit -m "fix: SKU mapping original_product_name field"
git push origin main

# 6. 同步到 EC2
bash scripts/sync_to_ec2.sh

# 7. 删除修复分支（可选）
git branch -d fix/20260604-sku-field
```

### 方式2：回滚工作流

当修复引入问题需要回滚时：

```bash
# 1. 找到上一个稳定的修复分支
git branch -a | grep fix/

# 2. 切换回 main 并重置到上一个稳定状态
git checkout main
git reset --hard origin/main

# 3. 或者切换到指定的修复分支
git checkout fix/20260603-original-fix
git checkout -B main  # 强制重置 main 到当前分支

# 4. 强制推送到远程
git push origin main --force
```

### 方式3：测评分支工作流

每次测评前创建专用测评分支（不影响开发进度）：

```bash
# 1. 创建测评分支（基于 main）
git checkout -b test/20260604-regression main

# 2. 执行测评（不改动代码）
python scripts/workflow.py \
  --skill-path skills/skill_order_to_huading_template \
  --action evaluate_only

# 3. 测评结果保存到报告
# docs/测评报告_20260604.md

# 4. 测评通过后，删除测评分支
git checkout main
git branch -D test/20260604-regression
```

---

## 分支保护规则

| 分支 | 保护规则 |
|------|---------|
| `main` | 必须通过测评后才能合并；禁止强制推送 |
| `fix/*` | 建议通过测评后合并 |
| `test/*` | 可自由创建，不强制要求测评通过 |

---

## 回滚方案对比

| 场景 | 推荐方案 | 操作 |
|------|---------|------|
| 小问题快速回滚 | `git revert` | 生成反向提交，保留历史 |
| 大问题回滚 | 切换到修复分支 | `git checkout fix/xxx && git checkout -B main` |
| 完全丢弃改动 | `git reset --hard` | 谨慎使用，仅本地有效 |
| EC2 回滚 | 重新同步旧文件 | rsync 指定旧版本到 EC2 |

---

## CI/CD 集成（可选）

```yaml
# .github/workflows/skill-test.yml
name: Skill Test & Repair

on:
  push:
    branches:
      - 'fix/*'
      - 'main'

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run Evaluation
        run: |
          python scripts/workflow.py \
            --skill-path skills/skill_order_to_huading_template \
            --action evaluate_only

      - name: Upload Report
        uses: actions/upload-artifact@v3
        with:
          name: evaluation-report
          path: docs/测评报告_*.md

  auto-repair:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run Auto Repair
        run: |
          python scripts/auto_repair.py \
            --skill-path skills/skill_order_to_huading_template \
            --action execute

      - name: Create PR
        run: |
          git checkout -b fix/auto-repair-$(date +%Y%m%d)
          git add -A
          git commit -m "fix: auto repair from evaluation"
          git push origin fix/auto-repair-$(date +%Y%m%d)
```

---

## 本地快速命令

```bash
# 快捷脚本：创建修复分支
bash scripts/git-helpers.sh create-fix "sku field fix"

# 快捷脚本：测评并创建修复分支
bash scripts/git-helpers.sh evaluate-and-fix

# 快捷脚本：回滚到上一个修复分支
bash scripts/git-helpers.sh rollback-last
```

---

## 分支维护

- `fix/*` 分支：合并后保留 30 天，之后自动删除
- `test/*` 分支：测评完成后即可删除
- `main` 分支：始终保持稳定，可直接部署
---
name: skill-skill-monitor
description: 监控所有 OpenClaw 工作区的 Skill 变动，自动更新版本号和 CHANGELOG，记录变更历史。当检测到 Skill 文件变化时，触发版本更新流程。
metadata:
  openclaw:
    triggers:
      - skill监控
      - 版本巡检
      - skill变动
      - 版本管理
    schedule:
      interval: 30min  # 定时扫描间隔
---

# skill-skill-monitor

## Overview

**Skill Name**: Skill 版本监控器

**Description**: 监控所有 openclaw-workspaces 下 Skill 的 Git 变更，自动执行版本记录。检测变更 → 判断版本级别 → 更新 CHANGELOG → 提交记录 → 飞书通知。

**Version**: 1.0.0

**目标**：让 Skill 版本管理**零人工介入**，每次改动自动留痕。

---

## 核心职责

1. **扫描** — 定时扫描所有 Skill 目录的 Git 变更
2. **检测** — 发现变更后解析改动内容
3. **定级** — 根据改动类型判断版本递增级别（patch/minor/major）
4. **记录** — 更新 VERSION 和 CHANGELOG.md
5. **通知** — 飞书推送变更摘要

---

## 监控范围

监控所有工作区目录：
```
~/openclaw-workspaces/
├── ai-order/skills/
├── ai-kefu/skills/
├── product-solution/skills/
├── project-manager/skills/
├── supply-chain-plan/skills/
├── BA/skills/
└── ...其他工作区...
```

每个工作区下 `skills/` 子目录里的 Skill 都是监控对象。

---

## 版本递增规则

| 改动类型 | 版本变化 | 示例 |
|---------|---------|------|
| 文档/注释/格式调整 | patch | 修改 SKILL.md 注释、README |
| Bug 修复 | patch | 修复某个解析 bug |
| 新增小功能 | minor | 新增一个工具函数、新增一个字段映射 |
| 功能优化/重构 | minor | 重构 order_parser、优化匹配算法 |
| 重大架构变化 | major | 拆库、分层重构、接口变化 |
| 删除功能 | major | 移除某个模块 |
| 数据库 schema 变化 | minor | 新增表、新增字段 |
| 配置变更 | patch | 修改 YAML 配置默认值 |

---

## 版本更新流程

```
[检测到 Git 变更]
      ↓
[解析改动文件列表]
      ↓
[判断主要改动类型]
      ↓
[确定新版本号]
      ↓
[更新 VERSION 文件]
      ↓
[追加 CHANGELOG 条目]
      ↓
[Git Add + Commit]
      ↓
[飞书通知变更摘要]
```

---

## CHANGELOG 条目格式

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Changed
- 优化了 SKU 匹配第三层逻辑，新增模糊匹配

### Added
- 新增字段映射规则：小江溪 → 创宇

### Fixed
- 修复了门店编号解析 bug

### Notes
- 对话 session: om_xxx | 2026-06-05 14:30
- 改动文件: tools/_sku_mapper.py, field_mapping/rules/小江溪.yaml
```

---

## 工具模块

### 1. git_scanner.py

扫描 Skill 的 Git 变更。

**主要函数：**
```python
def scan_all_skills() -> List[Dict]:
    """扫描所有工作区，返回有变更的 Skill 列表"""
    # 返回: [{workspace, skill_name, skill_path, changed_files, last_commit, last_commit_time}]

def get_skill_changes(skill_path: str) -> Dict:
    """获取单个 Skill 的详细变更信息"""
    # 返回: {files, diff_content, commit_msg, author, timestamp}
```

### 2. version_decider.py

判断版本递增级别。

**主要函数：**
```python
def decide_version_bump(changed_files: List[str], diff_content: str) -> str:
    """
    根据改动文件+diff内容判断版本变化
    返回: 'patch' | 'minor' | 'major'
    """
```

### 3. changelog_writer.py

写入 VERSION 和 CHANGELOG。

**主要函数：**
```python
def update_version(skill_path: str, new_version: str):
    """更新 VERSION 文件"""

def append_changelog(skill_path: str, entry: ChangelogEntry):
    """追加 CHANGELOG 条目"""

def commit_changes(skill_path: str, commit_msg: str):
    """Git add + commit"""
```

### 4. notifier.py

飞书通知。

**主要函数：**
```python
def notify_change(skill_name: str, old_version: str, new_version: str, entry: ChangelogEntry):
    """发送飞书消息通知变更"""
```

---

## 数据库设计

```sql
CREATE TABLE skill_version_history (
    id SERIAL PRIMARY KEY,
    skill_name TEXT NOT NULL,
    workspace TEXT NOT NULL,
    old_version TEXT,
    new_version TEXT NOT NULL,
    bump_type TEXT NOT NULL,          -- 'patch' | 'minor' | 'major'
    changed_files TEXT,              -- JSON 数组，变更文件列表
    changelog_entry TEXT,             -- CHANGELOG 正文
    commit_sha TEXT,                 -- Git commit SHA
    trigger_session TEXT,            -- 触发变更的 session（推测来源）
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_skill_version_skill ON skill_version_history(skill_name);
CREATE INDEX idx_skill_version_time ON skill_version_history(created_at);
```

---

## 定时巡检

通过 HEARTBEAT.md 配置定时触发：

```markdown
## Skill 版本巡检

每 30 分钟自动执行：
1. 扫描所有工作区 skills/ 目录
2. 检测 Git 变更
3. 如有变更 → 执行版本更新流程
4. 飞书通知结果
```

---

## 依赖

- Git（本地 `git diff`、`git log`、`git add`、`git commit`）
- 文件系统访问（`exec` 工具）
- 飞书推送（`message` 工具）
- 数据库（可选，用于历史记录）

---

## 输出示例

飞书推送格式：
```
🦎 Skill 版本更新

📦 skill_order_to_huading_template
   v5.8.0 → v5.8.1 (patch)

📝 变更内容：
   • 优化了 SKU 匹配第三层逻辑（新增模糊匹配）
   • 新增门店编号容错处理

📁 改动文件：
   tools/_sku_mapper.py
   field_mapping/rules/default.yaml

⏱️ 2026-06-05 14:30
```

---

## 架构

```
skill-skill-monitor/
├── SKILL.md
├── VERSION
├── CHANGELOG.md
├── __init__.py                   # 入口
├── tools/
│   ├── __init__.py
│   ├── git_scanner.py            # Git 变更扫描
│   ├── version_decider.py         # 版本级别判断
│   ├── changelog_writer.py        # 版本 + CHANGELOG 更新
│   └── notifier.py               # 飞书通知
└── sql/
    └── init_tables.sql           # 建表语句
```

---

## 实施计划

| Phase | 任务 | 状态 |
|-------|------|------|
| Phase 1 | Git 扫描 + 变更检测 | ✅ 已完成 |
| Phase 1 | 版本递增判断 | ✅ 已完成 |
| Phase 1 | CHANGELOG 写入 | ✅ 已完成 |
| Phase 1 | 飞书通知 | ✅ 已完成 |
| Phase 2 | 数据库持久化 | 待开发 |
| Phase 2 | 定时巡检集成 HEARTBEAT | 待开发 |

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0.0 | 2026-06-05 | 初始版本 |
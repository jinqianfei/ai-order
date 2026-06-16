# 记忆模块闭环升级方案 v1.0

**日期**：2026-06-16  
**项目**：AI建单助手  
**目标**：把现有本地记忆系统从“有协议和脚本”升级为“启动可召回、过程可追踪、结束可沉淀、日结可维护、质量可验证”的闭环。

---

## 1. 闭环链路

```text
启动检查
→ 按需读取 MEMORY / PROJECT / PENDING / sessions / credentials
→ 会话中产出和问题进入工作区文件
→ 会话结束写 session 总结
→ 更新 PROJECT / PENDING / skills / files / outputs 索引
→ extract_memory.py 回写 MEMORY.md 最近会话摘要
→ check_quality.py 做 4W 质量检查
→ reindex.py 重建 .memory_index
→ 下次启动通过 startup_check.py 主动发现过期、缺目录、版本不一致和紧急事项
```

---

## 2. 数据分层

| 层级 | 文件/目录 | 职责 |
|------|-----------|------|
| L1 总览 | `MEMORY.md` | 最近会话摘要、活跃版本、关键长期记忆 |
| L2 项目状态 | `memory/projects/ai-order/PROJECT.md` | 项目目标、架构、当前版本、模块状态 |
| L3 会话沉淀 | `memory/projects/ai-order/sessions/` | 每次结束会话的结构化总结 |
| L4 待办风险 | `memory/projects/ai-order/problems/PENDING.md` | 紧急项、进行中项、已完成项 |
| L5 索引 | `files/INDEX.md`、`outputs/INDEX.md`、`skills/INDEX.md`、`.memory_index/` | 文件、产物、Skill版本和全文检索 |
| L6 凭证索引 | `memory/credentials/INDEX.md` | 只记录凭证位置和使用规则，不明文泄露密码 |

---

## 3. 自动化维护

### 启动

运行：

```bash
python3 memory_system/scripts/startup_check.py
```

检查：
- `MEMORY.md` 是否新鲜
- `PENDING.md` 是否存在紧急项
- `PROJECT.md` 记录版本是否等于 `skills/skill_order_to_huading_template/VERSION`
- 项目记忆目录和索引是否齐全
- `memory/credentials/INDEX.md` 是否存在
- `.memory_index/index.json` 是否存在且非空

### 日结

`ops/daily_wrap.sh` 在原有日报后追加记忆维护：

```bash
python3 memory_system/scripts/extract_memory.py --apply --days 14
python3 memory_system/scripts/check_quality.py
python3 memory_system/scripts/reindex.py
```

### 结束会话

用户明确说“结束会话/再见/去忙别的吧”时，执行：

```text
SESSION_END_PROTOCOL
→ 写 sessions/<date>-<session>.md
→ 更新 sessions/INDEX.md
→ 更新 PROJECT.md / PENDING.md / skills/INDEX.md / files/INDEX.md / outputs/INDEX.md
→ 运行 extract_memory.py --apply
→ 运行 check_quality.py
```

---

## 4. 质量标准

每条重要记忆至少包含 4W：

| 字段 | 要求 |
|------|------|
| When | 发生日期或会话日期 |
| What | 客观事实、完成项或决策 |
| Why | 触发原因、用户要求或决策理由 |
| Witness | 文件路径、命令结果、版本号、报告或链接 |

质量门槛：
- `quality >= 0.8`：高质量
- `0.5 <= quality < 0.8`：可接受，但建议补证据
- `quality < 0.5`：需要补写

---

## 5. 本次升级任务

- [x] 生成本方案文档
- [x] 补齐 `sessions/files/outputs/skills` 索引结构
- [x] 补齐 `memory/credentials/INDEX.md` 模板
- [x] 增强 `startup_check.py`（6 项检查）
- [x] 将记忆维护步骤接入 `ops/daily_wrap.sh`
- [x] 更新 `PROJECT.md` 和 `PENDING.md` 到当前版本状态
- [x] 增加记忆闭环契约测试

---

## 6. 验证标准

必须通过：

```bash
python3 -m py_compile memory_system/scripts/*.py
python3 memory_system/scripts/startup_check.py --json
python3 memory_system/scripts/check_quality.py
python3 memory_system/scripts/reindex.py --check
python3 memory_system/scripts/test_memory_closed_loop.py
```

允许存在的外部限制：
- 飞书同步工具当前不可用时，本地文档先落地，飞书同步列为待补。
- 记忆质量检查对历史旧日志可能给出中/低质量提示，不阻断本次闭环。

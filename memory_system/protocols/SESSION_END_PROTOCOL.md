# 会话结束协议

**触发时机：** 当你告诉我"结束会话"、"再见"、"去忙别的吧"等结束信号时，我立即执行以下流程。

---

## 第一步：会话总结写入

写入路径：`memory/projects/<项目名>/sessions/<YYYY-MM-DD>-<会话ID>.md`

```markdown
# 会话总结 | YYYY-MM-DD | HH:MM-HH:MM

**会话ID：** session_xxx
**项目：** <项目名>
**持续时间：** X小时X分钟
**对话轮次：** N轮

---

## 📌 本次完成

- ...

## 🔧 修改的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| path/to/file | 新建/修改/删除 | 用途 |

##💡 关键决策

- 决策1：...
- 决策2：...

## ⚠️ 问题与卡点

- 问题1：[描述] → [解决方式/未解决]
- 问题2：...

## 📋 待跟进

- [ ] 待跟进事项1
- [ ] 待跟进事项2

## 🧠 AI 自我复盘

- 本次做得好的地方：...
- 需要改进的地方：...
- 学到的教训：...

---

*由 AI 助手自动生成 | 生成时间：YYYY-MM-DD HH:MM*
```

---

## 第二步：更新项目记录

对于涉及的项目，立即更新：
- `projects/<项目名>/sessions/INDEX.md` — 新增本次会话记录
- `projects/<项目名>/files/INDEX.md` — 新增/修改的长期文件列表
- `projects/<项目名>/outputs/INDEX.md` — 新增长期产出物列表
- `projects/<项目名>/problems/` — 本次遇到的问题
- `projects/<项目名>/skills/INDEX.md` — 本次使用的 skill 版本
- `projects/<项目名>/PROJECT.md` — 如有重大进展则更新

---

## 第三步：更新 MEMORY.md

- 提取本次会话的精华（关键决策、重大产出、待跟进事项）
- 写入 MEMORY.md 的「最近会话摘要」和「待办事项」

---

## 第四步：更新 TOOLS.md（如有变更）

- 新增的 SubAgent 配置
- 新增的脚本/工具路径
- 配置变更

---

## 第五步：凭证检查

- 如果本次会话涉及新的账号/密码/密钥 → 写入 `memory/credentials/INDEX.md`
- 只记录凭证位置和读取方式，不写明文密码、token 或 secret

---

## 第六步：更新未完成事项

将本次未完成的待办写入 `projects/<项目>/problems/PENDING.md`：
- 🔴 紧急：需要立即处理但暂时搁置的
- 🟡 进行中：本次未完成但需继续的
- ✅ 已完成：本次完成的（从进行中移到已完成）

格式见 `memory_system/protocols/PENDING_PROTOCOL.md`

---

## 第七步：运行记忆闭环维护

从工作区根目录执行：

```bash
python3 memory_system/scripts/extract_memory.py --apply --days 14
python3 memory_system/scripts/check_quality.py
python3 memory_system/scripts/reindex.py
python3 memory_system/scripts/startup_check.py
```

要求：
- `extract_memory.py --apply` 必须更新 `MEMORY.md` 的「最近会话摘要」
- `check_quality.py` 如发现低质量历史日志，不阻断本次结束，但要在 `PENDING.md` 记录待补
- `reindex.py` 必须重建 `.memory_index/index.json`
- `startup_check.py` 不应出现 fail；如出现 fail，先修复再结束

---

## 禁止行为

- ❌ 不确定的信息写入 MEMORY.md
- ❌ 猜测性的内容写入项目记录
- ❌ 忘记更新待跟进事项状态
- ❌ 不写自我复盘
- ❌ 写 session 日志后不更新 `sessions/INDEX.md`
- ❌ 更新 MEMORY.md 后不运行质量检查和索引重建

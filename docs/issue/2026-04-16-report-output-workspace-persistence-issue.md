# Issue Report: 报告产物缺少 output/task_id 文件化工作区

**日期**: 2026-04-16  
**类型**: Persistence / Report Writing Workflow  
**优先级**: P1  
**状态**: 已确认，暂不修复

---

## 背景

当前报告长度偏短、迭代修改能力弱。检查后发现，系统虽然已经有 PostgreSQL task/report persistence helper，但报告写作过程本身仍缺少一个面向论文写作 agent 的文件化工作区。

合理范式应当是：每个 task 在 `output/<task_id>/` 下形成独立写作目录，持续保存 metadata、检索材料、草稿、审阅意见、修订记录和最终 Markdown，而不是只把最终短文本塞进 task/result 字段。

---

## 当前表现

### 1. `/tasks` 运行态仍依赖内存 task store

代码位置：`src/api/routes/tasks.py`

当前存在 `_tasks: dict[str, TaskRecord]`，任务执行过程、SSE events、chat history、当前报告上下文都会先写入该内存对象。PostgreSQL snapshot 可作为长久化补充，但运行时主状态仍是内存对象。

### 2. 报告正文保存在字段里，而不是写作目录里

主要字段包括：

- `TaskRecord.result_markdown`
- `TaskRecord.draft_markdown`
- `TaskRecord.full_markdown`
- `TaskRecord.report_context_snapshot`
- `PersistedReport.content_markdown`

这些字段适合 API 展示和结果恢复，但不适合作为长报告的渐进式写作空间。

### 3. Artifact store 仍有内存实现

代码位置：

- `src/research/graph/nodes/persist_artifacts.py`
- `src/api/routes/workspaces.py`

两个模块都存在 in-memory artifact store。它们能支撑 UI 面板或临时调试，但不能作为报告写作过程的 durable source of truth。

---

## 为什么会导致报告短

报告生成当前更像“一次性生成结果”：

1. 检索和分析中间材料没有落到稳定的 task 文件夹中。
2. draft/review/revision 没有围绕同一个 `report.md` 反复编辑。
3. review feedback 不能直接生成 patch 或 revision draft。
4. 最终 API 返回倾向于展示一个字段里的 markdown，而不是一个可迭代的写作工件。

这会让系统更容易生成短摘要，而不是逐步扩展成完整论文式综述。

---

## 建议设计（暂不实现）

每个 task 创建如下目录：

```text
output/
  <task_id>/
    metadata.json
    brief.json
    search_plan.json
    rag_result.json
    paper_cards.json
    draft.md
    review_feedback.json
    revisions/
      001_initial.md
      002_after_review.md
    report.md
```

推荐规则：

- `metadata.json` 记录 task_id、workspace_id、source_type、report_mode、模型配置、创建/完成时间。
- 所有节点输出同时写入 PostgreSQL snapshot 和 `output/<task_id>/` 文件。
- draft/review/revision 应围绕 `draft.md -> revisions/* -> report.md` 迭代，而不是覆盖一个短字符串。
- `/tasks/{id}` 返回摘要字段；`/tasks/{id}/result` 返回最终报告；新增或扩展 export endpoint 负责打包整个 task workspace。
- 若后续继续遵守 “long-lived persistence must go through PostgreSQL”，则 output 目录应作为报告工件工作区，PostgreSQL 保存索引、状态和 content_ref。

---

## 验收标准

- 创建 research/report task 后，存在 `output/<task_id>/metadata.json`。
- 每个主要节点至少产生一个结构化中间文件。
- review 失败或要求修改时，新增 revision 文件，而不是只覆盖 `result_markdown`。
- 最终报告长度和结构由多轮写作工件累积产生，而不是单次 LLM 输出决定。
- `/tasks`, `/tasks/{id}`, `/tasks/{id}/result` 与 PostgreSQL 状态、output 文件引用保持一致。


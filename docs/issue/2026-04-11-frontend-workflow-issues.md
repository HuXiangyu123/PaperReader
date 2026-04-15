# 前端展示 & Workflow 完整性问题报告

> 生成时间：2026-04-11
> 状态：待修复

---

## 一、测试覆盖现状分析

### `tests/api/test_tasks.py` 覆盖范围

| # | 测试用例 | 验证内容 | 状态 |
|---|---------|---------|------|
| 1 | `test_list_tasks_empty` | GET `/tasks` 空列表 | ✅ |
| 2 | `test_create_task` | POST `/tasks` 返回 task_id + pending | ✅ |
| 3 | `test_get_task` | GET `/tasks/{id}` | ✅ |
| 4 | `test_get_task_not_found` | 404 | ✅ |
| 5 | `test_list_tasks_after_create` | 批量创建 | ✅ |
| 6 | `test_existing_report_endpoint_still_works` | `/report` 向后兼容 | ✅ |
| 7 | `test_task_chat` | POST `/tasks/{id}/chat` | ✅ |
| 8 | `test_research_task_trace_uses_task_id` | `/trace` 端点，验证 task_id 传递 | ⚠️ 需验证 |

### 测试缺口（未覆盖）

| # | 缺失测试 | 原因 |
|---|---------|------|
| T1 | Research workflow 完整流程（clarify → search_plan → review → persist） | 无 |
| T2 | Research task SSE event 流 | 无 |
| T3 | `GET /tasks/{id}/review` 端点 | 无 |
| T4 | `needs_followup=True` 触发追问表单 | 无 |
| T5 | Backend codex 修复后的死锁验证 | 无 |
| T6 | `useTaskDetail` hook 正确渲染 brief/search_plan | 无 |

### `test_research_task_trace_uses_task_id` 验证到哪

该测试（line 101-141）：
1. 创建 `TaskRecord`（research 模式）
2. Mock `run_clarify_agent` 返回 `needs_followup=False`
3. 调用 `_run_graph_sync_wrapper(task_id)` 同步执行
4. 请求 `GET /tasks/{task_id}/trace`
5. **断言 A**：`node_runs` 中至少有一个 run 的 `task_id == task.task_id`
6. **断言 B**：`{run["node_name"] for run in node_runs} >= {"review", "persist_artifacts"}`

**问题**：断言 B 期望 `review` 和 `persist_artifacts` 节点在 graph 中执行，但：

- 当前 research graph 路径：**clarify → search_plan → review → persist_artifacts**
- `run_clarify_node` 在 mock 层被替换，graph 实际从 `clarify` 开始
- `clarify` 返回后走 `_route_after_clarify`，`needs_followup=False` → 走 `search_plan`
- 但 `run_search_plan_node` 使用 **heuristic fast path**（`confidence=0.68 >= 0.6`）
- **search 节点根本不在 research graph 里！**

→ 断言 B **应该会通过**（review + persist_artifacts 确实在 graph 里），但测试只验证了 trace 传递，没有验证 search 阶段。

---

## 二、前端 JSON 展示问题

### 问题描述

Research task 完成后，`ReportPreview` 组件将 `brief` 和 `search_plan` 以纯 JSON 格式展示：

```jsx
// ReportPreview.tsx line 103-104
{task?.brief && <JsonSection title="Research Brief" data={task.brief} />}
{task?.search_plan && <JsonSection title="Search Plan" data={task.search_plan} />}
```

`JsonSection` 直接 `JSON.stringify(data, null, 2)` 渲染在深色 `<pre>` 块中。

### 用户期望 vs 实际

| 模块 | 用户期望 | 实际 |
|------|---------|------|
| Brief | 格式化卡片：topic 高亮、goal 描述、子问题列表 | 深色 JSON 代码块 |
| Search Plan | 可视化：query 列表、group 统计、coverage strategy badge | 深色 JSON 代码块 |
| Review Feedback | 结构化问题列表，通过/失败状态 | 深色 JSON 代码块 |
| Report（完成后） | Markdown 渲染 | ✅ 已正确渲染 |

### 根本原因

`ReportPreview` 对 research 模式的处理缺少专门的 UI 组件：

```89:126:frontend/src/components/ReportPreview.tsx
if (isResearchTask) {
    // ...
    {task?.brief && <JsonSection title="Research Brief" data={task.brief} />}
    {task?.search_plan && <JsonSection title="Search Plan" data={task.search_plan} />}
    // 没有对应的渲染组件，直接输出 JSON
```

`SessionOverview` 已有很好的可视化组件（`BriefCard`、`SearchStats`），但 `ReportPreview` 没有复用。

---

## 三、Workflow 完整性问题

### Research Graph 当前状态

```
clarify → search_plan → review → persist_artifacts → END
```

### 缺失的节点（Phase 2 规划中应有）

| 节点 | 规划描述 | 当前状态 |
|------|---------|---------|
| `search` | 执行 search_plan 中的查询 | ❌ **缺失**，graph 无此节点 |
| `extract` | 从搜索结果提取 paper cards | ❌ **缺失** |
| `draft` | 撰写综述草稿 | ❌ **缺失** |
| `repair` | 修复 review 失败 | ❌ **缺失** |

### 影响

1. **搜索未执行**：search_plan 生成了查询计划，但没有节点去执行它
2. **无法生成报告**：draft 节点缺失，无法产出 markdown 报告
3. **Phase 2 规划未落地**：module2.md 中的搜索→抽取→草稿流程完全没有实现

### SearchPlanAgent 实际做了什么

虽然 research graph 里没有 search 节点，但 `SearchPlanAgent.run()` 内部有 Agent Loop：
- 内部会调用 `_call_search_arxiv()` 等工具
- 但这些是 Agent 内部行为，不受 graph 状态管理
- 结果没有写入 graph state，也没有暴露给前端

### 正确的 Graph 应为

```
clarify → search_plan → search → extract → draft → review → repair? → persist_artifacts → END
```

---

## 四、综合问题清单

### P0（阻塞）

| # | 问题 | 文件 | 原因 |
|---|------|------|------|
| P0-1 | Research graph 缺少 `search`、`draft` 节点，无法生成报告 | `src/research/graph/builder.py` | Phase 2 实现缺失 |
| P0-2 | SearchPlanAgent 内部搜索结果未写入 graph state | `src/research/agents/search_plan_agent.py` | agent loop 独立于 graph |

### P1（严重）

| # | 问题 | 文件 | 原因 |
|---|------|------|------|
| P1-1 | ReportPreview 对 research mode 输出 JSON 而非可视化 | `frontend/src/components/ReportPreview.tsx:103-104` | 缺少 research 专用展示组件 |
| P1-2 | Brief JSON 展示无法理解内容结构 | `frontend/src/components/ReportPreview.tsx` | JsonSection 不适合展示结构化数据 |
| P1-3 | Search Plan JSON 展示，query_groups 等信息无法快速浏览 | `frontend/src/components/ReportPreview.tsx` | 同上 |

### P2（测试缺口）

| # | 问题 | 文件 | 原因 |
|---|------|------|------|
| T1 | 缺少 research workflow 端到端测试 | `tests/api/test_tasks.py` | 未实现 |
| T2 | 缺少 `GET /tasks/{id}/review` 测试 | `tests/api/test_tasks.py` | 未实现 |
| T3 | 缺少 `needs_followup=True` 追问流程测试 | `tests/api/test_tasks.py` | 未实现 |
| T4 | `test_research_task_trace_uses_task_id` 断言 B 逻辑需确认 | `tests/api/test_tasks.py:140` | 需验证 review/persist 是否真的会执行 |

### P3（体验优化）

| # | 问题 | 文件 | 原因 |
|---|------|------|------|
| E1 | AgentPanel 的 `/api/v1/agents` fetch 失败不影响 UI（静默失败） | `frontend/src/components/AgentPanel.tsx:79-84` | 无 loading/error 状态 |
| E2 | Agent run result 截断到 500 字符，信息不完整 | `frontend/src/components/AgentPanel.tsx:316` | 硬编码限制 |
| E3 | TraceTimeline 组件存在但数据来源不确定 | `frontend/src/components/TraceTimeline.tsx` | 无测试覆盖 |

---

## 五、修复优先级建议

### 第一阶段：修复 ReportPreview 展示（P1-1 ~ P1-3）

**方案**：复用 `SessionOverview` 中已有的可视化组件：

```tsx
// ReportPreview.tsx - research mode 部分
if (isResearchTask) {
    return (
        <div>
            {task?.brief && (
                <BriefCardSimple brief={task.brief} />
            )}
            {task?.search_plan && (
                <SearchPlanCard plan={task.search_plan} />
            )}
        </div>
    );
}
```

### 第二阶段：补全 Research Graph（P0-1 ~ P0-2）

需要在 `src/research/graph/builder.py` 中添加：
- `search` 节点：读取 `state["search_plan"]`，执行查询
- `extract` 节点：从搜索结果提取 paper cards
- `draft` 节点：基于 brief + paper cards 撰写报告

### 第三阶段：补全测试（P2）

---

## 六、已验证正常的模块

以下模块经端到端测试验证工作正常：

| 模块 | 验证方式 | 结果 |
|------|---------|------|
| ClarifyAgent policy fallback | `POST /tasks` + `GET /tasks/{id}` | ✅ `needs_followup=False` |
| 后台任务执行（死锁修复） | Codex 修复后端到端 | ✅ `status=completed` |
| SearchPlanAgent heuristic fast path | 同上 | ✅ `search_plan` 正常生成 |
| SSE event 流 | `useTaskSSE` hook | ✅ 连接正常 |
| Review 同步到 task record | `GET /tasks/{id}/review` | ✅ `review_passed=True` |
| SessionOverview 可视化 | 前端组件 | ✅ BriefCard/SearchStats 渲染正确 |
| Phase34Panel tab 切换 | 前端组件 | ✅ 5 个 tab 正常 |

---

## 七、调试建议

### 查看前端问题

打开浏览器 DevTools → Network，筛选 `/tasks/{taskId}`，检查返回值：

```json
{
  "status": "completed",
  "brief": { ... },
  "search_plan": { ... },
  "review_passed": true
}
```

如果 `brief` 和 `search_plan` 字段存在但前端显示为 JSON，说明是 ReportPreview 渲染问题（P1-1）。

### 确认 Graph 节点执行

检查 SSE event 流，看是否有 `node_end` 事件：

```
node_start: clarify
node_end: clarify
node_start: search_plan
node_end: search_plan
node_start: review      ← 应该存在
node_end: review
node_start: persist_artifacts
node_end: persist_artifacts
```

**如果缺少 `search`、`draft` 节点**，确认 graph builder 中是否添加了对应节点。

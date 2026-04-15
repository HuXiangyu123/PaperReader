# PaperReader Agent 开发日志

> 记录日期：2026-04-11
> 本次整理：前端交互 / Skills 注册 / Terminate+Export / 模型分层架构 / 长期记忆 / 前端刷新机制

---

## 一、问题分类与优先级

### P0（必须修复，影响数据正确性）

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| P0-1 | 前端"完整任务详情"不在运行中刷新 | `useTaskDetail` 单次拉取 + SSE 只推事件不回拉 task | 左侧/右侧面板显示旧数据 |
| P0-2 | workspace_id 未透传到 AgentPanel | `App.tsx` 未传 workspace_id，`AgentPanel` 用 taskId 代替 | agent/skill 接口上下文错位 |

### P1（影响性能和用户体验）

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| P1-1 | 单模型全链路（deepseek-reasoner 吃所有节点） | `settings.py` 只选一个 provider，所有节点复用 | 简单节点（search、extract）速度慢、成本高 |
| P1-2 | extract 非真正并行 | for-loop 顺序调用 LLM，每批 5 篇 | 20 篇论文时可达 3 分钟 |
| P1-3 | draft 无输入预算控制 | 最多 30 张卡片全部塞入一次调用 | reasoner 耗时过长 |
| P1-4 | 无节点级 timeout / time budget | 全局 `LLM_TIMEOUT_S=45s`，无 per-node 预算 | 某节点卡死影响整条链路 |

### P2（架构层，长期规划）

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| P2-1 | 无系统级 workflow memory | 任务聊天只带最近 8 条 + report_context_snapshot，`chat_summary` 字段存在但未使用 | 跨节点无长期记忆 |
| P2-2 | Skills 面板为空 | `get_skills_registry()` 从未调用 `discover_from_filesystem()` | 用户看不到可用 skills |
| P2-3 | terminate/export 按钮无效 | 后端无对应接口 | 用户无法停止任务或导出 |

---

## 二、P0 详细分析与修复方案

### P0-1：前端运行中不刷新任务详情

#### 现状链路

```
后端状态机：
  clarify → search_plan → search → extract → draft → review → persist_artifacts
                          ↓
                  search_node 写入 rag_result
                  extract_node 写入 paper_cards
                  draft_node   写入 draft_markdown
                  review_node  写入 review_feedback
                          ↓
              _run_graph_sync_wrapper() 同步到 task record
                          ↓
              GET /tasks/{id} 返回 _serialize_task()
```

#### 前端拉取逻辑问题

| 文件 | 行 | 行为 | 问题 |
|------|-----|------|------|
| `useTaskDetail.ts` | 17 | `taskId` 变化时调用一次 | 任务运行中 taskId 不变，不触发刷新 |
| `useTaskSSE.ts` | 38 | 只更新 `nodeEvents` | 不回拉完整 task，导致状态事件有但详情数据没有 |
| `ReportPreview.tsx` | 374 | `isDone` 才拉取 | 运行中看不到实时进展 |
| `SessionOverview.tsx` | 378 | 依赖 `useTaskDetail` | 数据和 ReportPreview 一样旧 |

#### 修复方案：Ordered Log + Cursor Tailing 模式

参考 AgentPane[^1] 和 starcite 的 SSE 可靠性设计[^2]，核心思路：**SSE 只负责推送增量事件，完整数据从持久化 store 读取**，而不是依赖 SSE 传输所有数据。

```
前端 SSE 事件：
  { type: "node_end", node: "search", data: { rag_result: {...} } }
                          ↓ 触发
前端状态更新逻辑：
  node_end 事件 → 更新 nodeStatuses
  node_end 事件 → 判断字段类型 → 更新本地缓存
      若 node === "extract"  → 更新 paperCards
      若 node === "draft"    → 更新 draftMarkdown
      若 node === "review"   → 更新 reviewFeedback
                          ↓
前端轮询（低频 backup）：
  每 10s 轮询 GET /tasks/{id}（仅在任务 RUNNING 时）
  或：前端维护 event log cursor，每次 SSE reconnect 带 Last-Event-ID 重放
```

具体实现改动：

1. **修改 `useTaskSSE.ts`**：在 `node_end` 事件处理中，增量更新 `paperCards`、`draftMarkdown`、`reviewFeedback` 等字段，不依赖全量回拉
2. **修改 `useTaskDetail.ts`**：增加一个 `refresh()` 方法，供 SSE 事件处理后主动调用
3. **修改 `ReportPreview.tsx`**：移除 `isDone` 限制，运行中即显示已有数据（BriefCard/SearchPlanCard 先渲染，PaperCardsSection/draft 等后续节点逐步填充）
4. **作为 backup**：Running 状态下每 15s 静默回拉一次 `GET /tasks/{id}`，确保即使 SSE 丢事件也不丢数据

### P0-2：workspace_id 未透传

#### 问题链路

```
POST /tasks（创建任务）
  → 后端返回 task.task_id + task.workspace_id
  → App.tsx 只把 taskId 传给 Phase34Panel
  → Phase34Panel → AgentPanel → taskId as workspace_id ❌
  → GET /workspaces/{workspace_id}/artifacts → 404
```

#### 修复方案

1. `App.tsx`：`useTaskDetail` 返回值增加 `workspaceId`，透传给 `Phase34Panel`
2. `Phase34Panel`：接收 `workspaceId` prop，向下传给 `AgentPanel` / `SkillPalette`
3. `AgentPanel`：用真实的 `workspaceId` 替代 `taskId`

---

## 三、P1 详细分析：模型分层架构

### 3.1 deepseek-reasoner 的真实限制

根据 DeepSeek 官方 API 文档[^3]：

| 特性 | deepseek-reasoner | deepseek-chat |
|------|-------------------|--------------|
| 上下文窗口 | 128K | 128K |
| max_tokens 默认/最大 | 32K / 64K | 4K / 8K |
| temperature 等采样参数 | **不生效**（设了也被忽略） | 正常 |
| reasoning_content 跨轮次 | **不拼接**（多轮上下文独立） | N/A |
| Function Calling | 不支持 | 支持 |
| 适用场景 | 复杂推理、多步分析 | 快检索、结构化抽取 |

**关键坑点**：`max_tokens` 在 reasoner 中包含 `reasoning_content + final answer`，给太大预算直接拉长耗时[^3]。

### 3.2 当前系统的节点分层

```
低复杂度节点（fast-path / 规则逻辑）：
  ✅ search_node           I/O 并行，非 LLM
  ⚠️  extract_node         LLM 结构化抽取，JSON 稳定性要求高
  ❌ review_node           当前用 ReviewerService LLM，可降级为规则检查

中复杂度节点（结构化生成，JSON 稳定性优先）：
  ❌ extract_node          批量 LLM 抽取，每批 5 篇
  ❌ search_plan (heuristic) 简单查询规划

高复杂度节点（长上下文综合）：
  ⚠️ draft_node           最多 30 张卡片全部塞入 max_tokens=8192
  ❌ report_frame          整段 Full document text 塞入
  ✅ task_chat             对话生成，可以继续用 reasoner
```

### 3.3 推荐模型分层配置

```
环境变量设计：

# 全局默认值（快模型用于低复杂度节点）
LLM_PROVIDER=deepseek
DEFAULT_MODEL=deepseek-chat

# 高复杂度节点专用（reasoner 留给这里）
HIGH_COMPLEXITY_MODEL=deepseek-reasoner

# Per-node 覆盖（可选，细粒度控制）
EXTRACT_MODEL=deepseek-chat
DRAFT_MODEL=deepseek-reasoner
REVIEW_MODEL=deepseek-chat   # review 主要是规则逻辑，不需要 reasoner

# 运行时参数
LLM_TIMEOUT_S=30             # 从默认值 45s 降到 30s
LLM_MAX_RETRIES=0           # 禁用重试，快速失败
```

### 3.4 输入规模控制（比调参更有效）

| 节点 | 当前 | 建议 | 节省 |
|------|------|------|------|
| extract | 每批 5 篇，20 篇 = 4 批 × 45s ≈ 3min | 每批 2-3 篇，或加并发 | ~50% 时间 |
| draft | 最多 30 张卡片全塞 | 降至 10-15 张卡片 | ~60% 推理 token |
| draft max_tokens | 8192 | 4096-6144（reasoner 输出预算压缩） | ~50% 耗时 |
| extract max_tokens | 8192 | 2048-4096 | ~50% 耗时 |

### 3.5 节点级 Time Budget 控制

当前全局 `LLM_TIMEOUT_S=45s` 无法 per-node 控制。建议：

```python
# settings.py 扩展
NODE_TIME_BUDGETS = {
    "extract": 30,      # 秒
    "draft": 60,
    "review": 20,
    "clarify": 45,
    "search_plan": 30,
    "default": 30,
}
```

每个 LLM 调用前，根据当前节点查 budget，传给 `build_chat_llm(timeout=...)`。

---

## 四、P2 详细分析：长期记忆与上下文压缩

### 4.1 当前记忆现状

```
任务创建 → report_context_snapshot（静态快照，不更新）
    ↓
chat_history（最近 8 条）
    ↓
chat_summary（字段存在，但从未被写入）
    ↓
search_plan 内部 memory（单节点局部）
```

### 4.2 长期记忆分层架构（参考工程实践）

参考 Factory[^4]、Kognaize[^5]、Zylos Research[^6] 的多层记忆设计：

```
┌─────────────────────────────────────────────────────────┐
│  L1: Working Context（LangGraph state，所有节点共享）    │
│  包含：brief, search_plan, paper_cards, draft_markdown  │
│  节点间通过 state dict 传递                           │
└─────────────────────────────────────────────────────────┘
         ↓ 节点完成后压缩归档
┌─────────────────────────────────────────────────────────┐
│  L2: Episodic Memory（每轮对话/任务完成后）             │
│  结构：{intent, changes, decisions, next_steps}         │
│  来自 chat_summary 字段 + 节点执行摘要                 │
│  实现：任务完成时自动调用 LLM 生成摘要                  │
└─────────────────────────────────────────────────────────┘
         ↓ 跨任务检索
┌─────────────────────────────────────────────────────────┐
│  L3: Semantic Memory（向量存储）                       │
│  基于 workspace_id，存储所有历史 artifact               │
│  下一轮 search_plan 可先检索相关历史                    │
│  实现：persist_artifacts_node 已写入 workspace          │
└─────────────────────────────────────────────────────────┘
```

### 4.3 上下文压缩策略优先级

1. **最优先（低成本高回报）**：extract 每批 5→2-3 篇 + 摘要截断 1000→500 字
2. **次优先（中成本）**：draft 30 张卡片降至 10-15 张
3. **长期（高成本高回报）**：实现 rolling summarization，每次对话后压缩 chat_history

---

## 五、Skills 系统修复

### 问题

`src/skills/registry.py` 的 `get_skills_registry()` 只注册了 4 个内置 skills，从未调用 `discover_from_filesystem()` 扫描 `.agents/skills` 和 `.claude/skills` 目录。

### 修复

首次调用时自动扫描文件系统，已注册的内置 skills 不会被覆盖。

### 当前可用 Skills（内置）

| skill_id | 名称 | backend | 适用 Agent |
|----------|------|---------|-----------|
| research_lit_scan | Research Literature Scan | MCP_TOOLCHAIN | RETRIEVER |
| paper_plan_builder | Paper Plan Builder | LOCAL_GRAPH | ANALYST |
| creative_reframe | Creative Reframe | MCP_PROMPT | PLANNER |
| workspace_policy_skill | Workspace Policy Skill | LOCAL_FUNCTION | SUPERVISOR |

---

## 六、后端新增接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/tasks/{id}/terminate` | POST | 标记任务为 FAILED，前端收到 SSE done 事件后停止轮询 |
| `/tasks/{id}/export` | GET | 导出完整 Markdown 报告（Research 模式含 Brief+SearchPlan+Draft；Report 模式直接导出 markdown）|

---

## 七、2026-04-11 下午修复记录

### Fix 1: TaskHistory 刷新丢失（P0）

**问题**：页面刷新后历史任务列表消失，TaskHistory 只在 `activeTaskId` 存在时才渲染。

**根因**：
1. `App.tsx` 中 `TaskHistory` 包裹在 `{activeTaskId && (...)}` 中——刷新后 React state 丢失，条件不满足就消失
2. `TaskHistory.tsx` 的 `useEffect` 只在 `refreshTrigger` 变化时触发，初次挂载时不加载

**修复**：
- `App.tsx`：移除 `{activeTaskId && ...}` 条件，TaskHistory 始终可见
- `TaskHistory.tsx`：修复 `useEffect` 依赖，`refreshTrigger` 作为 refresh 触发器
- 增加 loading 状态和空状态提示

### Fix 2: ModelConfigPanel 点击无效（P1）

**问题**：ModelConfigPanel 点了 Save 按钮后端无变化，因为 Settings 是 immutable dataclass。

**根因**：后端 Settings 在启动时从 `.env` 读取，无运行时写入能力；前端的 Save 编辑功能完全是空操作。

**修复**：重写 `ModelConfigPanel.tsx`：
- 移除虚假的编辑/保存功能
- 改为只读展示：当前 Provider、Reason Model、Quick Model、各模型用途
- 增加 Provider API Key 配置状态指示（绿色/灰色圆点）
- 增加黄色提示框：说明修改方式为编辑 `.env` 后重启后端
- 支持切换 provider 显示各 provider 的可用模型列表

---

## 八、工程建议总结

### 立即可做（1-2 天）

1. **P0-1**：修改 `useTaskSSE.ts`，在 `node_end` 事件中增量更新各字段；ReportPreview 运行中即可渲染已有数据
2. **P0-2**：`App.tsx` 透传 `workspaceId` 到 Phase34Panel
3. **P1 参数调优**：`.env` 设置 `LLM_TIMEOUT_S=30`，`LLM_MAX_RETRIES=0`；extract 每批 5→2-3 篇

### 本周规划（3-5 天）

4. **P1 模型分层**：settings.py 支持 per-node 模型配置；extract/review 切到 deepseek-chat；draft 保留 deepseek-reasoner
5. **P1 输入预算**：draft 30→10-15 cards；extract max_tokens 8192→2048-4096

### 架构迭代（1-2 周）

6. **P2-1 L2 记忆**：任务完成时调用 LLM 生成 `chat_summary`，写入 task record
7. **P2-2 L3 记忆**：利用现有 `workspace artifacts` 实现跨任务检索，search_plan 前先查历史
8. **extract 真并行**：将 LLM 调用 submit 到 ThreadPoolExecutor，真正并行

---

## 参考资料

[^1]: [AgentPane - Ben Gubler](https://www.bengubler.com/posts/2026-03-05-introducing-agentpane) — SSE + SQLite 双写，ring buffer 重放
[^2]: [Why Agent UIs Lose Messages on Refresh - starcite](https://starcite.ai/blog/why-agent-uis-lose-messages-on-refresh) — Ordered immutable log + cursor-based tailing
[^3]: [DeepSeek Reasoner API Docs](https://api-docs.deepseek.com/guides/reasoning_model) — max_tokens 包含 reasoning_content，跨轮次不拼接
[^4]: [Working Memory Compression - Muthu](https://notes.muthu.co/2026/03/working-memory-compression-and-context-distillation-in-long-horizon-agents/) — rolling summarization，Factory 36K session 评估
[^5]: [Context Management in AI Agents with LangGraph - Kognaize](https://www.kognaize.com/blog/context-management-for-agents) — LLM 写入/Select/Compress 四策略
[^6]: [AI Agent Context Compression: Strategies - Zylos Research](https://zylos.ai/research/2026-02-28-ai-agent-context-compression-strategies) — hierarchical memory + relevance scoring

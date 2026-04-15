# Issue Report: LangGraph Agent 工作流代码冗余与架构问题

**日期**: 2026-04-16
**类型**: Architecture / Code Quality / Critical
**优先级**: P0
**状态**: 新建

---

## Executive Summary

当前 agent 工作流存在**三层架构冗余**：

1. **Graph 层**（`src/research/graph/builder.py`）：7 节点线性 StateGraph
2. **Supervisor 层**（`src/research/agents/supervisor.py`）：包装 Graph 层的元编排器
3. **Agent 层**（`src/research/agents/*.py`）：5 个独立 LangGraph Agent

这三层之间存在大量重复状态定义、交叉依赖、未使用的协议接口、以及互相矛盾的设计承诺。

---

## Issue 1: 两套 State 定义造成状态冗余

### 问题描述

同一个研究状态在三处被重复定义为不同的 TypeDict：

```python
# 第一处：Graph 层状态
src/graph/state.py::AgentState
  → brief, search_plan, rag_result, paper_cards, draft_report, ...

# 第二处：Supervisor 层包装状态
src/research/agents/supervisor.py::SupervisorGraphState
  → workflow_state: dict[str, Any]  # ← 包裹 AgentState 的 untyped dict
  → payload: dict[str, Any]
  → collaboration_trace: list  # 重复的状态追踪

# 第三处：每个 Agent 的独立状态
src/research/agents/planner_agent.py::PlannerGraphState
src/research/agents/analyst_agent.py::AnalystGraphState
src/research/agents/retriever_agent.py::RetrieverGraphState
src/research/agents/reviewer_agent.py::ReviewerGraphState
src/research/agents/clarify_agent.py::ClarifyGraphState
src/research/agents/search_plan_agent.py::SearchPlanGraphState
```

### 根因

| 层级 | 状态类型 | 问题 |
|------|---------|------|
| Graph 层 | `AgentState` (TypedDict) | 真实状态在此定义 |
| Supervisor 层 | `workflow_state: dict` (untyped) | 包装 Graph 状态，但只透传不增强 |
| Agent 层 | 各 Agent 独立 TypedDict | 每个 agent 定义自己的状态，但结果写回 `workflow_state` |

### 冗余代码

- `SupervisorGraphState.payload` 字段从未在 `collaborate()` 执行路径中被使用
- `HandoffSupervisorState.research_state` 是 `dict` 类型，没有 schema 约束
- `collaboration_trace` 在 Supervisor 层追踪，又在 `_build_trace_entry` 中重复收集字段

### 修复建议

删除 `SupervisorGraphState.payload`，将 `workflow_state` 改为直接引用 `AgentState`，Agent 层状态合并到 Graph 层状态中。

---

## Issue 2: Supervisor 两套执行路径并行存在

### 问题描述

`AgentSupervisor` 实现了**两套完全不同的执行路径**：

```python
# 路径 A：确定性图编排（默认）
supervisor.collaborate()
  → self.build_graph()  # StateGraph，包含 9 个节点（prepare + 7 CANONICAL + finalize）
  → 顺序执行 CANONICAL_NODE_ORDER

# 路径 B：LLM Handoff 编排（未使用）
supervisor.collaborate_with_handoff()
  → self.build_official_supervisor_graph()  # langgraph-supervisor 包
  → LLM 决定下一个调用哪个 agent
```

### 证据

| 方法 | 代码行 | 调用位置 | 状态 |
|------|-------|---------|------|
| `build_graph()` | 405-426 | `collaborate()` 第 586 行 | 活跃 |
| `build_official_supervisor_graph()` | 428-471 | `collaborate_with_handoff()` 第 533 行 | 未被调用 |
| `build_handoff_agent()` | 473-486 | `build_handoff_agents()` | 未被调用 |
| `build_handoff_agents()` | 488-490 | `build_official_supervisor_graph()` | 未被调用 |
| `collaborate_with_handoff()` | 515-566 | 无 | 从未被调用 |

### 影响

- `build_handoff_agents()` 中的每个 handoff agent 都构建了**独立的 LangGraph**，拥有自己的 checkpointer namespace
- 这些独立的 checkpointer 没有被 supervisor 的 checkpointer 管理
- 代码行 473-490 的所有 handoff agent 构建逻辑从未被执行

### 冗余代码清单

| 文件 | 代码行 | 描述 |
|------|-------|------|
| `supervisor.py` | 122-129 | `HandoffSupervisorState` TypedDict，从未使用 |
| `supervisor.py` | 358-363 | `_build_default_handoff_model()`，从未被调用 |
| `supervisor.py` | 364-389 | `_build_handoff_user_message()`，从未被调用 |
| `supervisor.py` | 391-403 | `_format_handoff_agent_message()`，从未被调用 |
| `supervisor.py` | 428-471 | `build_official_supervisor_graph()`，从未被调用 |
| `supervisor.py` | 473-490 | `build_handoff_agent()` + `build_handoff_agents()`，从未被调用 |
| `supervisor.py` | 515-566 | `collaborate_with_handoff()`，从未被调用 |

---

## Issue 3: V2 Agent Targets 与 LEGACY_NODE_TARGETS 的未对齐

### 问题描述

V2 Agent Targets 定义了 4 个节点的 V2 实现，但 `clarify`、`extract`、`persist_artifacts` 没有 V2 版本：

```python
V2_AGENT_TARGETS = {
    "search_plan": {"module": "...planner_agent", "fn": "run_planner_agent", ...},
    "search": {"module": "...retriever_agent", "fn": "run_retriever_agent", ...},
    "draft": {"module": "...analyst_agent", "fn": "run_analyst_agent", ...},
    "review": {"module": "...reviewer_agent", "fn": "run_reviewer_agent", ...},
}

LEGACY_NODE_TARGETS = {
    "clarify": ("src.research.graph.nodes.clarify", "run_clarify_node"),
    "search_plan": ("src.research.graph.nodes.search_plan", "run_search_plan_node"),
    "search": ("src.research.graph.nodes.search", "search_node"),
    "extract": ("src.research.graph.nodes.extract", "extract_node"),
    "draft": ("src.research.graph.nodes.draft", "draft_node"),
    "review": ("src.research.graph.nodes.review", "review_node"),
    "persist_artifacts": ("src.research.graph.nodes.persist_artifacts", "persist_artifacts_node"),
}
```

### 问题

1. **`clarify` 节点在两个地方被实现**：
   - Graph 层：`src/research/graph/nodes/clarify.py` 调用 `run_clarify_node`
   - Agent 层：`src/research/agents/clarify_agent.py` 有完整的 LangGraph ClarifyAgent
   - 但 `clarify_agent.py` 没有被 `V2_AGENT_TARGETS` 引用

2. **提取逻辑重复**：
   - `extract_node`（Graph 层）有自己的 extract 逻辑
   - `AnalystAgent._build_structured_cards`（Agent 层）也有 extract 逻辑

3. **`_has_v2_backend()` 的含义模糊**：
   ```python
   def _has_v2_backend(self, node_name: str) -> bool:
       return node_name in V2_AGENT_TARGETS
   ```
   对于 `clarify`、`extract`、`persist_artifacts`，这个方法总是返回 False。

---

## Issue 4: SearchPlanAgent 与 PlannerAgent 功能重叠

### 问题描述

两个 Agent 都声称负责 "Search Plan 生成"：

| 属性 | `SearchPlanAgent` | `PlannerAgent` |
|------|------------------|----------------|
| 文件 | `search_plan_agent.py` | `planner_agent.py` |
| 主入口 | `run()` | `run()` |
| 使用 LangGraph | ✅ | ✅ |
| Paradigm | "Bounded Agent Loop" | "Plan-and-Execute" |
| 调用位置 | Graph 层 `search_plan` 节点 | Supervisor V2 backend |
| 状态管理 | `SearchPlanGraphState` | `PlannerGraphState` |
| 记忆管理 | `SearchPlannerMemory` (Pydantic) | `MemoryManager` (本进程) |
| Checkpointer | `search_plan_agent` namespace | `planner_agent` namespace |

### 根因

- Graph 层的 `search_plan` 节点调用 `run_search_plan_node`，而 `run_search_plan_node` 内部调用 `SearchPlanAgent.run()`
- 如果 V2 模式启用，Supervisor 调用 `run_planner_agent`（`PlannerAgent.run()`）
- 两个 Agent **独立执行**，共享 `workspace_id` 但没有状态共享

### 冗余代码

- `src/research/agents/search_plan_agent.py` 整个文件（约 535 行）
- `src/models/research.py` 中的 `SearchPlannerMemory`（如果仅被 SearchPlanAgent 使用）

---

## Issue 5: Agent Paradigm 枚举值与实际 Agent 不匹配

### 问题描述

```python
# src/models/config.py
class AgentParadigm(Enum):
    PLAN_AND_EXECUTE = "plan_and_execute"        # → PlannerAgent ✅
    TAG = "tag"                                  # → RetrieverAgent ✅
    REASONING_VIA_ARTIFACTS = "reasoning_via_artifacts"  # → AnalystAgent ✅
    REFLEXION = "reflexion"                      # → ReviewerAgent ✅
    LEGACY = "legacy"                            # → Graph 层节点
```

但 `V2_AGENT_TARGETS` 中的 `paradigm` 字段使用的是**错误的枚举值**：

```python
V2_AGENT_TARGETS = {
    "search_plan": {
        "paradigm": AgentParadigm.PLAN_AND_EXECUTE.value,  # "plan_and_execute"
        "fn": "run_planner_agent",                          # PlannerAgent ✅ 正确
    },
    "search": {
        "paradigm": AgentParadigm.TAG.value,                # "tag"
        "fn": "run_retriever_agent",                        # RetrieverAgent ✅ 正确
    },
    "draft": {
        "paradigm": AgentParadigm.REASONING_VIA_ARTIFACTS.value,  # "reasoning_via_artifacts"
        "fn": "run_analyst_agent",                          # AnalystAgent ✅ 正确
    },
    "review": {
        "paradigm": AgentParadigm.REFLEXION.value,          # "reflexion"
        "fn": "run_reviewer_agent",                          # ReviewerAgent ✅ 正确
    },
}
```

实际上这个映射是正确的。但问题在于：

- `ClarifyAgent` 没有被映射到任何 `AgentParadigm` 值（它是独立的 LangGraph agent）
- `SearchPlanAgent` 也没有被映射到 `AgentParadigm`（它是 Graph 层的一部分）

---

## Issue 6: MemoryManager 与 PostgreSQL 的断层

### 问题描述

`MemoryManager`（`src/memory/manager.py`）声称是 "LangGraph checkpoint-aware runtime memory adapter"，但实际上：

1. **所有存储都是进程内的**：
   - `_events`: `RuntimeEventBuffer` — Python list，50 条上限
   - `_working`: `RuntimeWorkingState` — Python dataclass
   - `_vectors`: `RuntimeVectorCache` — Python list + numpy，500 条上限
   - `_episodes`: `RuntimeEpisodeLog` — Python list，100 条上限
   - `_preferences`: `RuntimePreferenceStore` — Python dict

2. **`checkpointer` 属性从未被使用**：
   ```python
   self._checkpointer = checkpointer or get_langgraph_checkpointer(f"memory:{workspace_id}")
   ```
   虽然 `MemoryManager` 持有一个 `BaseCheckpointSaver`，但这个 checkpointer 从未被用于持久化任何状态。

3. **状态不能跨进程恢复**：
   如果 uvicorn 进程重启，所有 MemoryManager 中的数据丢失。

### 根因

代码注释已经承认了这个问题：

```python
"""MemoryManager — LangGraph checkpoint-aware runtime memory adapter.

The runtime-facing API is intentionally small and transient. Earlier versions
persisted semantic/episodic/preference memory as JSON files under ``.memory``;
that violates the current project rules. This module now keeps short-lived
memory in process and exposes a LangGraph ``BaseCheckpointSaver`` for graph
state ownership.
"""
```

### 影响

- `PlannerAgent`、`RetrieverAgent`、`AnalystAgent`、`ReviewerAgent` 都使用 `MemoryManager` 记录状态
- 这些状态在进程重启后丢失
- `ReviewerAgent` 的 Reflexion 反思存储在 `RuntimeVectorCache` 中，重启后无法恢复

---

## Issue 7: 未使用的 Supervisor 基础设施

### 问题描述

`AgentSupervisor` 中定义了多个从未被实例化的基础设施：

#### 1. `NodeBackend` Protocol

```python
class NodeBackend:
    async def run(self, state: dict, inputs: dict) -> dict:
        raise NotImplementedError
```

- 定义了 `NodeBackend` Protocol
- `AgentSupervisor` 有 `_node_backends: dict[str, NodeBackend]` 字段
- 但从未调用 `self._node_backends.get(node_name)` — 代码实际上用的是 `LEGACY_NODE_TARGETS` 动态 import
- `register_backend()` 方法从未被调用

#### 2. `_result_payload()` 方法

```python
def _result_payload(self, workflow_state: dict, trace: list[dict[str, Any]], summary: str, mode: str) -> dict:
```

- 定义完整，返回值包含所有 `RESULT_STATE_KEYS`
- 但 `collaborate()` 实际返回 `result.get("supervisor_result") or {}`
- `_finalize_collaboration_node()` 构建了自己的 `supervisor_result` dict

#### 3. `_prune_state_for_stage()` 方法

```python
async def replan(self, state: dict, trigger_reason: str, target_stage: str = "search_plan") -> dict:
    new_state = self._prune_state_for_stage(state, canonical)
    payload = {"replan": True, "reason": trigger_reason}
    return await self.collaborate(new_state, start_node=canonical, inputs=payload)
```

- `replan()` 调用 `collaborate()`，后者重新构建 `build_graph()`
- 但 `build_graph()` 使用 `canonical_start` 参数控制起始节点
- `_prune_state_for_stage()` 手动删除下游字段，但 `collaborate()` 内部的状态合并是直接覆盖

#### 4. `_summarize_trace()` 和 `_summarize_handoff_trace()`

- `_summarize_trace()` 在 `_finalize_collaboration_node()` 中使用
- `_summarize_handoff_trace()` 定义但从未被调用（因为 `collaborate_with_handoff()` 不存在）

---

## Issue 8: LEGACY_NODE_ALIASES 未被使用

### 问题描述

```python
LEGACY_NODE_ALIASES: dict[str, str] = {
    "plan_search": "search_plan",
    "search_corpus": "search",
    "extract_cards": "extract",
    "synthesize": "draft",
    "write_report": "draft",
    "revise": "review",
}
```

- 这些别名在 `normalize_node_name()` 中被引用
- 但没有证据表明有任何代码传入这些旧别名
- `_route_after_node()` 直接使用 `CANONICAL_NODE_ORDER` 索引，不经过别名解析

---

## Issue 9: Graph 层与 Agent 层的循环依赖

### 问题描述

```
src/research/graph/builder.py
    ↓ imports
src/research/graph/nodes/clarify.py
    ↓ imports
src/research/agents/clarify_agent.py
    ↓ contains
LangGraph graph (clarify_agent 自己的)

src/research/agents/supervisor.py
    ↓ imports
V2_AGENT_TARGETS → planner_agent / retriever_agent / analyst_agent / reviewer_agent
    ↓
Agent 层各自有独立的 LangGraph

src/research/graph/nodes/search.py
    ↓ 直接调用
src/tools/search_tools.py
```

### 具体问题

- `clarify_agent.py` 是一个完整的 LangGraph agent（`build_clarify_agent_graph()`）
- 但 Graph 层把它当作一个**函数**（`run_clarify_node`）来调用
- `AnalystAgent` 内部调用 `_build_markdown()` 从 `draft.py`，造成 agent → graph 的反向依赖

---

## Issue 10: ClarifyAgent 的双重实现

### 问题描述

`clarify` 节点在两个地方实现：

1. **`src/research/agents/clarify_agent.py`**：
   - `build_clarify_agent_graph()`：完整的 LangGraph，包含 7 个节点
   - 支持 `structured_output` → `json_parse` → `repair` → `limited` 的分层降级策略
   - 主入口：`run()` 函数

2. **`src/research/graph/nodes/clarify.py`**：
   - `run_clarify_node()` 函数
   - 内部直接调用 `clarify_agent.run()`
   - 包装层，添加了 `current_stage` 设置

### 冗余

- Graph 层的 `clarify` 节点是一个无意义的 wrapper
- 如果要使用 ClarifyAgent 的完整 LangGraph 能力，应该直接在 V2 Agent Targets 中映射

---

## 冗余代码清单汇总

| 文件 | 代码行 | 冗余类型 | 建议 |
|------|-------|---------|------|
| `supervisor.py` | 122-129 | `HandoffSupervisorState` 未使用 | 删除 |
| `supervisor.py` | 358-403 | handoff 相关方法 | 删除 |
| `supervisor.py` | 428-490 | 第二套 supervisor 实现 | 删除 |
| `supervisor.py` | 515-566 | `collaborate_with_handoff()` | 删除 |
| `supervisor.py` | 105-109 | `NodeBackend` Protocol + `register_backend()` | 删除 |
| `supervisor.py` | 665-741 | `_prune_state_for_stage()` | 合并到 `collaborate()` |
| `supervisor.py` | 665-741 | `replan()` 中 prune 逻辑 | 简化 |
| `supervisor.py` | 335-346 | `_result_payload()` | 合并到 `_finalize_collaboration_node()` |
| `supervisor.py` | 329-333 | `_summarize_handoff_trace()` | 删除 |
| `supervisor.py` | 47-54 | `LEGACY_NODE_ALIASES` | 删除 |
| `search_plan_agent.py` | 1-535 | 与 PlannerAgent 功能重叠 | 评估是否合并 |
| `memory/manager.py` | 43-663 | `_events/_working/_vectors/_episodes/_preferences` | 标记为 transient |
| `graph/nodes/clarify.py` | 1-108 | ClarifyAgent wrapper | 删除 wrapper，直接调用 agent |
| `graph/nodes/draft.py` | 512-513 | `AnalystAgent` 引用 `_build_markdown` | 改为 agent 层输出 |

---

## 架构建议

### 短期（删除冗余）

1. 删除 `supervisor.py` 中所有 handoff 相关代码（Issue 2）
2. 删除 `LEGACY_NODE_ALIASES`（Issue 8）
3. 删除 `NodeBackend` Protocol 和未使用的 `_node_backends` 逻辑（Issue 7）
4. 评估 `SearchPlanAgent` vs `PlannerAgent` 的合并必要性（Issue 4）

### 中期（架构对齐）

5. 将 ClarifyAgent 接入 V2 Agent Targets，消除 wrapper（Issue 10）
6. 将 MemoryManager 的 checkpointer 属性实际用于状态持久化（Issue 6）
7. 统一状态定义：删除 `SupervisorGraphState.workflow_state` 的 dict 包装，使用 TypedDict

### 长期（LangGraph 规范合规）

8. 遵循 `langgraph.supervisor` 或 `langgraph_sdk.multi_agent` 规范重构 Supervisor
9. 消除 Graph 层 → Agent 层的循环依赖
10. 将所有 agent 实现统一为 LangGraph 节点或 tool，避免三层并行

---

## 附录：执行路径追踪

```
前端 POST /api/v1/tasks
  → tasks.py::_run_graph()
  → build_research_graph()          # Graph 层 StateGraph（7 节点）
  → graph.stream()                  # LangGraph 执行
  → 各节点调用 graph/nodes/*.py 中的函数
  → run_clarify_node()              # 调用 clarify_agent.run()
  → run_search_plan_node()          # 调用 SearchPlanAgent.run()
  → search_node()                    # 直接工具调用
  → extract_node()                  # 直接处理
  → draft_node()                    # 直接处理
  → review_node()                    # 调用 ReviewerService
  → persist_artifacts_node()        # 写入内存存储

（AgentSupervisor.collaborate() 从未被 tasks.py 调用）
（V2 Agent Targets 永远不会被执行）
```

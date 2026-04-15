# Issue Report: Agent 架构未生效 + Agent 实现不使用 LangGraph

**日期**: 2026-04-13  
**类型**: Architecture / Critical Bug  
**状态**: Issue 1 Fixed, Issue 2 Acknowledged

---

## Executive Summary

项目设计了两套并行架构：
1. **Agent 层** (`src/research/agents/`) — 声称实现多种 Agent 范式（Plan-and-Execute、TAG、RVA、Reflexion）
2. **Graph 层** (`src/research/graph/builder.py`) — LangGraph StateGraph，硬编码路由

实际运行时，系统**完全绕过 Agent 层**，直接跑 Graph 层。Agent 定义形同虚设。

---

## Issue 1: Agent 层未被调用

### 问题描述

前端生成研究报告时，调用路径为：

```
/api/v1/tasks → _run_graph() → build_research_graph() → LangGraph StateGraph
                ↓ 完全绕过
                AgentSupervisor.collaborate() ← 永远不会被调用
```

### 根因

`src/api/routes/tasks.py` 的 `_run_graph()` 函数中，`source_type == "research"` 分支直接实例化 `build_research_graph()`：

```python
# src/api/routes/tasks.py:911-926 (修复前)
if source_type == "research":
    from src.research.graph.builder import build_research_graph
    
    emitter = NodeEventEmitter()
    emitter.events = task.node_events

    graph = build_research_graph(emitter)  # ← 直接用 Graph，不走 AgentSupervisor
    ...
```

`AgentSupervisor.collaborate()` 只在 `/api/v1/agents/run` 路径被调用，但前端不调用这个 API。

### 影响

| 维度 | 影响 |
|------|------|
| **Agent 范式** | Plan-and-Execute、TAG、RVA、Reflexion 永远不会被执行 |
| **V2 后端** | `V2_AGENT_TARGETS` 配置永远不会被使用 |
| **节点路由** | 永远是硬编码的 `clarify → search_plan → search → extract → draft → review → persist_artifacts` |
| **Memory** | Agent 级别的 Memory 集成（`get_memory_manager`）永远不会被调用 |

### 修复方案

修改 `tasks.py` 的 `_run_graph()`，将 `source_type == "research"` 分支改为调用 `AgentSupervisor.collaborate()`：

```python
# src/api/routes/tasks.py:937-960 (修复后)
if source_type == "research":
    from src.research.agents.supervisor import get_supervisor
    
    supervisor = get_supervisor()
    initial_state: dict = {
        **_build_state_template(...),
        "source_type": "research",
        "raw_input": task.input_value,
    }

    # Use AgentSupervisor.collaborate() instead of raw graph streaming
    result = await asyncio.to_thread(
        _run_supervisor_sync,
        supervisor,
        initial_state,
        task.node_events,
    )

    # AgentSupervisor.collaborate() returns state fields at root level
    state_result = result if result else {}
```

新增辅助函数 `_run_supervisor_sync()` 用于在线程中运行异步的 `supervisor.collaborate()`。

### 验证方法

1. 创建新的 research 类型任务
2. 检查 `node_events` 中的 `_backend_mode` 和 `_agent_paradigm` 字段
3. 预期：`_backend_mode=v2`, `_agent_paradigm=plan_and_execute/tag/reasoning_via_artifacts/reflexion`

---

## Issue 2: Agent 实现不使用 LangGraph

### 问题描述

`src/research/agents/` 下的所有 Agent 实现（`planner_agent.py`, `retriever_agent.py`, `analyst_agent.py`, `reviewer_agent.py`, `clarify_agent.py`）均为**纯 Python 类**，没有使用 LangGraph 库。

### 证据

```bash
$ grep -r "langgraph" src/research/agents/
# 无结果
```

各 Agent 的 import 语句：

| Agent 文件 | 依赖 |
|-----------|------|
| `planner_agent.py` | `logging`, `typing`, `src.memory.manager`, `src.agent.llm` |
| `retriever_agent.py` | `logging`, `typing`, `src.memory.manager`, `src.tools.search_tools` |
| `analyst_agent.py` | `logging`, `dataclasses`, `typing`, `src.memory.manager`, `src.skills.research_skills` |
| `reviewer_agent.py` | `logging`, `dataclasses`, `typing`, `src.memory.manager`, `src.research.services.reviewer` |
| `clarify_agent.py` | `langchain_core.messages`, `src.agent.llm`, `src.research.prompts.*` |

### 分析

1. **Agent 定义层面**：纯 Python 类，手动实现了各自范式的流程
   - `PlannerAgent`: Plan → Execute → Validate 三阶段
   - `RetrieverAgent`: Query Gen → Parallel Retrieval → Context Assembly
   - `AnalystAgent`: L0-L4 工件构建 DAG
   - `ReviewerAgent`: Actor → Evaluator → Self-Reflector 循环

2. **LangGraph 使用情况**：
   - LangGraph **仅在 Graph 层使用**（`src/research/graph/builder.py`）
   - Agent 层完全独立于 LangGraph

3. **架构设计意图**（推测）：
   - Agent 层：定义"如何做"（业务逻辑/范式）
   - Graph 层：定义"做什么"（工作流/路由）
   - AgentSupervisor：桥接两者，通过配置决定节点用 LEGACY 代码还是 V2 Agent

### 影响评估

| 场景 | 影响 |
|------|------|
| **架构一致性** | Agent 声称实现"Plan-and-Execute"等范式，但没有被 LangGraph 驱动，不符合业界对"Agent"的定义 |
| **可观测性** | Agent 内部没有 LangGraph 的 `node`/`edge`/`checkpoint` 机制 |
| **持久化** | Agent 执行状态不能被 LangGraph checkpoint 保存/恢复 |
| **实际功能** | 目前无影响，因为 Agent 层根本没被调用 |

### 可能的改进方向

#### Option A: Agent 实现保持独立，通过 AgentSupervisor 编排（当前架构）

```
AgentSupervisor.collaborate()
    ↓
for node in CANONICAL_NODE_ORDER:
    if node == "search_plan":
        run_planner_agent()  # ← 纯 Python Agent 作为节点实现
    elif node == "search":
        run_retriever_agent()  # ← 纯 Python Agent
```

**优点**：简单，Agent 逻辑独立测试  
**缺点**：不是"真正的 Agent"（没有工具调用循环、没有 ReAct 推理）

#### Option B: 将 Agent 重写为 LangGraph 节点

```python
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

# Plan-and-Execute as LangGraph
graph = StateGraph(AgentState)
graph.add_node("plan", planner_agent_node)  # LLM 规划
graph.add_node("execute", executor_node)    # 执行计划
graph.add_edge("plan", "execute")
```

**优点**：真正的 LLM 驱动路由，支持循环/条件/回退  
**缺点**：较大工程量，需要重写 Agent 实现

#### Option C: 混合架构

- Graph 层：定义高层的 `clarify → search → draft → review` 节点
- Agent 层：每个节点内部用 LangGraph 实现 ReAct 循环

---

## Issue 3: AgentSupervisor 的 LEGACY/V2 切换逻辑

### 问题描述

即使修复了 Issue 1，`AgentSupervisor` 的 LEGACY/V2 切换逻辑也可能导致 Agent 层仍然不被使用：

```python
def _get_backend_mode(self, node_name: str) -> NodeBackendMode:
    canonical = self.normalize_node_name(node_name)
    node_mode = self.config.node_backends.mode_for(canonical)
    
    if execution_mode == ExecutionMode.LEGACY:
        return NodeBackendMode.LEGACY  # ← V2 Agent 永远不会被调用
    if execution_mode == ExecutionMode.V2 and self._has_v2_backend(canonical):
        return NodeBackendMode.V2
```

如果配置文件设置 `ExecutionMode.LEGACY`，则 V2 Agent 不会被使用。

### 检查方法

```bash
curl http://localhost:8000/api/v1/config | jq '.execution_mode'
```

预期值：`V2` 才能启用 Agent 层。

---

## 总结

| Issue | 严重性 | 状态 |
|-------|--------|------|
| Issue 1: Agent 层未被调用 | Critical | ✅ Fixed |
| Issue 2: Agent 不使用 LangGraph | Medium | Acknowledged (Architecture Decision) |
| Issue 3: LEGACY/V2 配置 | Low | Needs Verification |

### 修复清单

- [x] 修改 `tasks.py` 使 `source_type=research` 走 `AgentSupervisor.collaborate()`
- [ ] 确认配置文件中 `execution_mode=V2`
- [ ] 验证新任务使用 V2 后端（检查 `collaboration_trace._backend_mode=v2`）
- [ ] （可选）将 Agent 重写为 LangGraph 节点（Option B）

---

## 复盘：为什么之前没发现

1. **只修症状，不追链路**：每次 debug 直接跳进相关文件，从没问"谁在调这些节点"
2. **架构文档 ≠ 实际行为**：代码设计和实际运行路径不一致，没人发现
3. **前端表现没有区分度**：两套系统产出相同结果，用户看不出版本差异
4. **缺乏执行路径验证**：没有机制验证"配置想用 V2，实际是不是真的在用 V2"

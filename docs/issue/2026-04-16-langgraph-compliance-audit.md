# Issue Report: LangGraph 规范合规性审查（修订版）

**日期**: 2026-04-16
**类型**: LangGraph Compliance / Architecture
**优先级**: P0
**参考文档**: LangGraph 官方文档（Context7 MCP，2026-04）

---

## 核心违规：手工 Supervisor + Dispatch 模式

规则原文：

> **Multi-agent supervisor**: Must use `langgraph.supervisor` or `langgraph_sdk.multi_agent`, never implement supervisor logic with Python class + dispatch pattern.

本地 `AgentSupervisor` 正是规则的直接违规：

```python
# src/research/agents/supervisor.py
class AgentSupervisor:
    """Research multi-agent supervisor with aliasing, resume, and handoff tracing."""

    def __init__(self, config: Phase4Config | None = None):
        self.config = config or Phase4Config()
        self._node_backends: dict[str, NodeBackend] = {}  # ← dispatch 表

    def dispatch(self, node_name: str, ...):
        backend_mode = self._get_backend_mode(node_name)
        if backend_mode == NodeBackendMode.LEGACY:
            return self._run_legacy(canonical, state, payload)
        elif backend_mode == NodeBackendMode.V2:
            return self._run_v2(canonical, state, payload)
```

这就是"Python class + dispatch pattern"，是规则明确禁止的。

---

## 官方 LangGraph Supervisor 规范

### 官方 Pattern：`create_supervisor`

```python
from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent

# Worker agents 用 create_react_agent 创建
research_agent = create_react_agent(
    model=model,
    tools=[web_search],
    name="research_expert"
)

math_agent = create_react_agent(
    model=model,
    tools=[add, multiply],
    name="math_expert"
)

# 用 create_supervisor 编排（不是 Python class + dispatch）
workflow = create_supervisor(
    [research_agent, math_agent],
    model=model,
    prompt="You are a team supervisor..."
)

app = workflow.compile()
result = app.invoke({"messages": [...]})
```

**关键差异**：

| 方面 | 官方模式 | 本地实现 |
|------|---------|---------|
| Supervisor 类型 | `create_supervisor()` 函数返回 Pregel agent | `class AgentSupervisor` Python 类 |
| Worker 类型 | `create_react_agent` 返回 Pregel agent | 纯 Python 函数包装 |
| Handoff 机制 | `Command(goto=agent, graph=Command.PARENT)` | `_merge_state()` 手工状态合并 |
| 路由决策 | LLM 自动决定 | Python dispatch 硬编码 |
| Message 历史 | 自动管理 | 手工 `collaboration_trace` |

---

## 违规详解

### 违规 1：手工 `AgentSupervisor` 类替代官方 `create_supervisor`

**文件**：`src/research/agents/supervisor.py`

```python
# 违规代码
class AgentSupervisor:
    def __init__(self, config: Phase4Config | None = None):
        self.config = config or Phase4Config()
        self._node_backends: dict[str, NodeBackend] = {}  # ← 手工 dispatch 表

    def _get_backend_mode(self, node_name: str) -> NodeBackendMode:
        canonical = self.normalize_node_name(node_name)
        node_mode = self.config.node_backends.mode_for(canonical)
        if node_mode != NodeBackendMode.AUTO:
            return node_mode
        # ... 手工条件判断

    def dispatch(self, node_name: str, state: dict, inputs: dict) -> dict:
        backend_mode = self._get_backend_mode(node_name)
        if backend_mode == NodeBackendMode.LEGACY:
            return self._run_legacy(canonical, state, payload)
        # ...
```

**应该用的官方 API**：

```python
from langgraph_supervisor import create_supervisor

workflow = create_supervisor(
    [clarify_agent, search_agent, draft_agent, review_agent],
    model=model,
    prompt="You coordinate research agents. Delegate to the most relevant agent..."
)
app = workflow.compile()
```

---

### 违规 2：手工 `_merge_state()` 替代官方 `Command` Handoff

**文件**：`src/research/agents/supervisor.py` 第 281-285 行

```python
# 违规代码：手工状态合并
def _merge_state(self, state: dict, result: dict) -> None:
    for key, value in result.items():
        if key.startswith("_"):
            continue
        state[key] = value  # ← 直接覆盖，没有消息传递机制
```

**官方 Handoff 机制**：

```python
from langgraph.types import Command

# 官方：agent 之间通过 Command 传递控制权
def handoff_to_agent(state):
    return Command(
        goto="research_expert",
        graph=Command.PARENT,  # 返回父图
        update={
            "messages": messages + [tool_message],
            "active_agent": "research_expert",
        }
    )
```

---

### 违规 3：手工 `collaboration_trace` 替代官方 Message History

**文件**：`src/research/agents/supervisor.py` 第 116-117 行

```python
# 违规代码：手工追踪
class SupervisorGraphState(TypedDict, total=False):
    collaboration_trace: list[dict[str, Any]]  # ← 手工 trace
    last_node: str | None
```

**官方模式**：`HandoffSupervisorState` 自动管理 messages：

```python
# 官方：messages 列表自动管理
class HandoffSupervisorState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    # agent 返回后，messages 自动合并
```

---

### 违规 4：独立的多个 LangGraph 而非统一的 Supervisor Graph

**问题**：本地实现有 7 个独立的 LangGraph：

```
planner_agent     → 独立 LangGraph (checkpointer: "planner_agent")
analyst_agent     → 独立 LangGraph (checkpointer: "analyst_agent")
retriever_agent  → 独立 LangGraph (checkpointer: "retriever_agent")
reviewer_agent   → 独立 LangGraph (checkpointer: "reviewer_agent")
clarify_agent    → 独立 LangGraph (checkpointer: "clarify_agent")
search_plan_agent → 独立 LangGraph (checkpointer: "search_plan_agent")
supervisor       → 独立 LangGraph (checkpointer: "agent_supervisor")
```

**官方模式**：单一 Supervisor Graph，所有 worker 作为节点或子图：

```python
# 官方：单一 supervisor graph
workflow = create_supervisor([research_agent, math_agent], ...)
app = workflow.compile(checkpointer=checkpointer)  # 单一 checkpointer
```

---

## 实际合规的部分

以下部分**符合** LangGraph 规范：

### 1. Graph 层使用 StateGraph ✅

```python
# src/research/graph/builder.py
g = StateGraph(AgentState)
g.add_node("clarify", run_clarify_node)
g.add_edge(START, "clarify")
g.add_conditional_edges("clarify", _route_after_clarify, {...})
return g.compile()
```

### 2. Checkpoint 接口 ✅

```python
# src/agent/checkpointing.py
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = MemorySaver()  # 或 PostgresSaver
graph.compile(checkpointer=checkpointer)
```

### 3. 条件边路由 ✅

```python
# src/research/graph/builder.py
def _route_after_review(state: dict) -> str:
    return "persist_artifacts" if state.get("review_passed") else END

g.add_conditional_edges("review", _route_after_review, {...})
```

### 4. TypedDict State 定义（部分）✅

```python
# src/research/agents/clarify_agent.py
class ClarifyGraphState(TypedDict, total=False):
    input: ClarifyInput
    brief: ResearchBrief | None
    warnings: list[str]
```

---

## 合规性评分

| 规范项 | 评分 | 说明 |
|-------|------|------|
| Supervisor 使用官方 API | 0/10 | 手工 `AgentSupervisor` 类 |
| Worker 使用官方 API | 0/10 | 纯 Python 函数 |
| Handoff 机制 | 0/10 | `_merge_state()` 而非 `Command` |
| Message History 管理 | 0/10 | 手工 `collaboration_trace` |
| 单一 Checkpointer | 0/10 | 7 个独立 checkpointer |
| 图编排（不用循环） | 5/10 | Graph 层合规，Supervisor 层违规 |
| Checkpoint 接口 | 8/10 | 接口正确，配置分散 |
| TypedDict State | 6/10 | 大部分使用，少量 untyped dict |

**总分：19/80 (24%)**

---

## 修复方案

### 方案 A：使用官方 `langgraph_supervisor`（推荐）

```python
from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent

# 1. 将每个 Agent 转为 create_react_agent
clarify_agent = create_react_agent(
    model=model,
    tools=[clarify_tool],
    name="clarify"
)

search_agent = create_react_agent(
    model=model,
    tools=[search_arxiv, searxng_search],
    name="search"
)

draft_agent = create_react_agent(
    model=model,
    tools=[draft_report_tool],
    name="draft"
)

review_agent = create_react_agent(
    model=model,
    tools=[review_tool],
    name="review"
)

# 2. 用 create_supervisor 编排（消除 AgentSupervisor 类）
workflow = create_supervisor(
    [clarify_agent, search_agent, draft_agent, review_agent],
    model=model,
    prompt="You coordinate a research workflow. "
           "Start with clarify to understand the research goal. "
           "Then use search to find relevant papers. "
           "Use draft to generate a report. "
           "Use review to validate the report."
)

app = workflow.compile(checkpointer=checkpointer)
result = app.invoke({"messages": [HumanMessage(content=user_input)]})
```

### 方案 B：使用 `langgraph_sdk.multi_agent`

```python
from langgraph_sdk import get_client

client = get_client()

# 创建 workers
client.agents.create(name="clarify", ...)
client.agents.create(name="search", ...)
client.agents.create(name="draft", ...)

# 创建多 agent 编排
assistant = client.assistants.create(
    graph_id="research_supervisor",
    config={...}
)
```

---

## 附录：LangGraph Supervisor 官方文档

- **包**：`langgraph-supervisor` (pip install langgraph-supervisor)
- **GitHub**: https://github.com/langchain-ai/langgraph-supervisor-py
- **核心 API**：
  - `create_supervisor(agents, model, prompt)` — 创建 supervisor workflow
  - `create_handoff_tool(agent_name, name, description)` — 自定义 handoff tool
  - `Command(goto, graph, update)` — agent 间控制权转移

Phase 4 只是在节点内部和工具层引入 `planner / retriever / analyst / reviewer` 多角色、`mcp_adapter.py`、skills、re-plan。你的 PRD 里也明确了：Phase 4 只做更强的 multi-agent 与 MCP，补 `mcp_adapter.py`、多角色拆分和 re-plan，而外层 orchestrator 仍然是研究工作流中枢。

---

## 一、推荐目录落点

```text
src/
  models/
    agent.py
    mcp.py
    skills.py
    config.py

  research/
    agents/
      supervisor.py
      planner_agent.py
      retriever_agent.py
      analyst_agent.py
      reviewer_agent.py

    backends/
      plan_search/
        legacy.py
        v2_agent.py
      search_corpus/
        legacy.py
        v2_agent.py
      extract_cards/
        legacy.py
        v2_agent.py
      review/
        legacy.py
        v2_agent.py

  tools/
    registry.py
    runtime.py
    specs.py
    mcp_adapter.py
    providers/
      local_provider.py
      corpus_provider.py
      mcp_provider.py
      skill_provider.py

  skills/
    registry.py
    runner.py
    manifests/

  api/
    routes/
      agents.py
      skills.py
      mcp.py
      config.py
```

这个目录是兼容式改法：
不改 `research/graph/nodes/*.py` 的现有位置，只新增 `agents/`、`backends/`、`skills/` 和 `tools/mcp_adapter.py`，与你前面已经确定的推荐框架路径是一致的。

---

## 二、Pydantic schema 设计

# 1）`src/models/config.py`

先把最关键的“执行模式”定下来，不然后面没法灰度迁移。

```python
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, ConfigDict, Field


class ExecutionMode(str, Enum):
    LEGACY = "legacy"
    HYBRID = "hybrid"
    V2 = "v2"


class AgentMode(str, Enum):
    AUTO = "auto"
    PLANNER = "planner"
    RETRIEVER = "retriever"
    ANALYST = "analyst"
    REVIEWER = "reviewer"


class NodeBackendMode(str, Enum):
    LEGACY = "legacy"
    V2 = "v2"
    AUTO = "auto"


class NodeBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarify: NodeBackendMode = NodeBackendMode.LEGACY
    plan_search: NodeBackendMode = NodeBackendMode.AUTO
    search_corpus: NodeBackendMode = NodeBackendMode.AUTO
    extract_cards: NodeBackendMode = NodeBackendMode.AUTO
    synthesize: NodeBackendMode = NodeBackendMode.AUTO
    review: NodeBackendMode = NodeBackendMode.AUTO
    revise: NodeBackendMode = NodeBackendMode.V2
    write_report: NodeBackendMode = NodeBackendMode.AUTO


class Phase4Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_mode: ExecutionMode = ExecutionMode.HYBRID
    agent_mode: AgentMode = AgentMode.AUTO
    enable_mcp: bool = True
    enable_skills: bool = True
    enable_replan: bool = True
    node_backends: NodeBackendConfig = Field(default_factory=NodeBackendConfig)
```

### 这层的意义

- `legacy`：全走 Phase 1/2/3 老逻辑
- `hybrid`：优先走新 agent/backend，失败回退旧逻辑
- `v2`：全走新 Phase 4 逻辑

这正好符合你现在的诉求：**先同时实现，再删 Phase 1 老逻辑**。

---

# 2）`src/models/agent.py`

这一层描述多角色 agent 的注册、运行、路由和 re-plan。

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.models.config import AgentMode


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    PLANNER = "planner"
    RETRIEVER = "retriever"
    ANALYST = "analyst"
    REVIEWER = "reviewer"


class AgentVisibility(str, Enum):
    AUTO = "auto"
    EXPLICIT = "explicit"
    BOTH = "both"


class AgentDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    role: AgentRole
    title: str
    description: str
    visibility: AgentVisibility = AgentVisibility.BOTH
    supported_skills: list[str] = Field(default_factory=list)
    supported_nodes: list[str] = Field(default_factory=list)


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    task_id: str | None = None
    role: AgentRole | None = None
    mode: AgentMode = AgentMode.AUTO
    node_name: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    preferred_skill_id: str | None = None


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"agr_{uuid4().hex[:12]}")
    workspace_id: str
    task_id: str | None = None
    role: AgentRole
    selected_skill_id: str | None = None
    output_artifact_ids: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
    summary: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReplanTrigger(str, Enum):
    REVIEWER = "reviewer"
    RETRIEVER = "retriever"
    USER = "user"


class ReplanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    task_id: str
    trigger: ReplanTrigger
    reason: str
    target_stage: Literal["clarify", "plan_search", "search_corpus"] = "plan_search"
    inputs: dict[str, Any] = Field(default_factory=dict)


class ReplanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replan_id: str = Field(default_factory=lambda: f"rpl_{uuid4().hex[:12]}")
    workspace_id: str
    task_id: str
    trigger: ReplanTrigger
    target_stage: str
    output_artifact_ids: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
```

### 这层对应的兼容逻辑

Phase 1 里真正 iterative 的只有 `SearchPlanAgent`，并明确要求外层 `StateGraph` 是 control plane，不能把每个 phase 都改成 agent。Phase 4 这里并不是反着来，而是把 agent 变成**节点内部协作角色**，由 `AgentSupervisor` 统一调度。

---

# 3）`src/models/mcp.py`

这一层是 `mcp_adapter.py` 的正式 schema。

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class MCPServerTransport(str, Enum):
    STDIO = "stdio"
    REMOTE = "remote"


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    name: str
    transport: MCPServerTransport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: HttpUrl | None = None
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    workspace_scoped: bool = False
    auth_ref: str | None = None


class MCPCapability(str, Enum):
    TOOLS = "tools"
    RESOURCES = "resources"
    PROMPTS = "prompts"
    APPS = "apps"


class MCPToolDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    tool_name: str
    title: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = True
    tags: list[str] = Field(default_factory=list)


class MCPPromptDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    prompt_name: str
    title: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class MCPResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str
    resource_uri: str
    title: str
    description: str
    mime_type: str | None = None
    tags: list[str] = Field(default_factory=list)


class MCPInvokeKind(str, Enum):
    TOOL = "tool"
    PROMPT = "prompt"
    RESOURCE = "resource"


class MCPInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    task_id: str | None = None
    server_id: str
    kind: MCPInvokeKind
    name_or_uri: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    require_user_approval: bool = True


class MCPInvocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invocation_id: str = Field(default_factory=lambda: f"mcp_{uuid4().hex[:12]}")
    workspace_id: str
    task_id: str | None = None
    server_id: str
    kind: MCPInvokeKind
    name_or_uri: str
    result_summary: dict[str, Any] = Field(default_factory=dict)
    trace_refs: list[str] = Field(default_factory=list)
```

### 这层为什么必须先 formalize

因为你 PRD 里已经指出当前 demo 的 `Tool Runtime / MCP / Skills` 是最弱的一层：没有 MCP adapter，tool schema 还是占位，所以 Phase 4 这里必须先把 schema 和 adapter 立住，否则 skills / MCP / multi-agent 都会飘。

---

# 4）`src/models/skills.py`

skills 必须是一等对象，而不是散落 prompt。

```python
from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.models.agent import AgentRole


class SkillBackend(str, Enum):
    LOCAL_GRAPH = "local_graph"
    LOCAL_FUNCTION = "local_function"
    MCP_PROMPT = "mcp_prompt"
    MCP_TOOLCHAIN = "mcp_toolchain"


class SkillVisibility(str, Enum):
    AUTO = "auto"
    EXPLICIT = "explicit"
    BOTH = "both"


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    name: str
    description: str
    backend: SkillBackend
    visibility: SkillVisibility = SkillVisibility.BOTH
    default_agent: AgentRole
    tags: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_artifact_type: str | None = None
    backend_ref: str


class SkillRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    task_id: str | None = None
    skill_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    preferred_agent: AgentRole | None = None


class SkillRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_run_id: str = Field(default_factory=lambda: f"skr_{uuid4().hex[:12]}")
    workspace_id: str
    task_id: str | None = None
    skill_id: str
    backend: SkillBackend
    output_artifact_ids: list[str] = Field(default_factory=list)
    trace_refs: list[str] = Field(default_factory=list)
    summary: str | None = None
```

### 建议首批内置 skills

你前面希望参考开源 repo 借鉴 3-4 个加入工作流。这里最自然的是把它们先做成 manifest，不急着都实现 backend：

- `research_lit_scan`
- `paper_plan_builder`
- `creative_reframe`
- `workspace_policy_skill`

这些都可以作为前端显式调用项。

---

## 三、FastAPI 接口草案

下面分四组接口：

- config
- agents
- skills
- mcp

---

# 1）`src/api/routes/config.py`

这一层用于前端切换 `legacy / hybrid / v2`。

```python
from pydantic import BaseModel, ConfigDict

from src.models.config import Phase4Config


class GetConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: Phase4Config


class UpdateConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: Phase4Config
```

```python
from fastapi import APIRouter

from src.api.routes.config_schemas import GetConfigResponse, UpdateConfigRequest
from src.models.config import Phase4Config

router = APIRouter(prefix="/api/v1/config", tags=["config"])


@router.get("/phase4", response_model=GetConfigResponse)
async def get_phase4_config():
    # TODO: read workspace/global config
    return GetConfigResponse(config=Phase4Config())


@router.post("/phase4", response_model=GetConfigResponse)
async def update_phase4_config(req: UpdateConfigRequest):
    # TODO: persist config
    return GetConfigResponse(config=req.config)
```

### 作用

让前端能显式切：

- `execution_mode = legacy / hybrid / v2`
- agent 自动/手动模式
- MCP / skills / re-plan 开关

---

# 2）`src/api/routes/agents.py`

```python
from pydantic import BaseModel, Field, ConfigDict

from src.models.agent import AgentDescriptor, AgentRunRequest, AgentRunResponse, ReplanRequest, ReplanResponse


class ListAgentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AgentDescriptor] = Field(default_factory=list)
```

```python
from fastapi import APIRouter

from src.api.routes.agent_schemas import ListAgentsResponse
from src.models.agent import (
    AgentDescriptor,
    AgentRole,
    AgentRunRequest,
    AgentRunResponse,
    ReplanRequest,
    ReplanResponse,
)

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", response_model=ListAgentsResponse)
async def list_agents():
    return ListAgentsResponse(items=[
        AgentDescriptor(
            agent_id="supervisor",
            role=AgentRole.SUPERVISOR,
            title="Supervisor",
            description="Routes tasks to planner/retriever/analyst/reviewer",
            supported_nodes=["plan_search", "search_corpus", "extract_cards", "review"],
        ),
        AgentDescriptor(
            agent_id="planner",
            role=AgentRole.PLANNER,
            title="Planner Agent",
            description="Builds and revises SearchPlan",
            supported_nodes=["clarify", "plan_search"],
            supported_skills=["creative_reframe"],
        ),
        AgentDescriptor(
            agent_id="retriever",
            role=AgentRole.RETRIEVER,
            title="Retriever Agent",
            description="Runs corpus retrieval and external academic search",
            supported_nodes=["search_corpus"],
            supported_skills=["research_lit_scan"],
        ),
        AgentDescriptor(
            agent_id="analyst",
            role=AgentRole.ANALYST,
            title="Analyst Agent",
            description="Builds PaperCards, matrix, outline, draft",
            supported_nodes=["extract_cards", "synthesize", "write_report"],
            supported_skills=["paper_plan_builder"],
        ),
        AgentDescriptor(
            agent_id="reviewer",
            role=AgentRole.REVIEWER,
            title="Reviewer Agent",
            description="Checks coverage, claims, citations, duplication",
            supported_nodes=["review", "revise"],
        ),
    ])


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(req: AgentRunRequest):
    # TODO: dispatch to AgentSupervisor / specific role agent
    raise NotImplementedError


@router.post("/replan", response_model=ReplanResponse)
async def replan(req: ReplanRequest):
    # TODO: trigger plan_search/search_corpus stage rerun
    raise NotImplementedError
```

### 这组接口干什么

给前端的 **Agent Switcher** 用。
也就是说，用户可以显式点：

- Auto
- Planner
- Retriever
- Analyst
- Reviewer

而不是只能走全自动。

---

# 3）`src/api/routes/skills.py`

```python
from pydantic import BaseModel, Field, ConfigDict

from src.models.skills import SkillManifest, SkillRunRequest, SkillRunResponse


class ListSkillsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SkillManifest] = Field(default_factory=list)
```

```python
from fastapi import APIRouter, HTTPException

from src.api.routes.skill_schemas import ListSkillsResponse
from src.models.agent import AgentRole
from src.models.skills import (
    SkillBackend,
    SkillManifest,
    SkillRunRequest,
    SkillRunResponse,
    SkillVisibility,
)

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


@router.get("", response_model=ListSkillsResponse)
async def list_skills():
    return ListSkillsResponse(items=[
        SkillManifest(
            skill_id="research_lit_scan",
            name="Research Literature Scan",
            description="Initial multi-source candidate paper scan",
            backend=SkillBackend.MCP_TOOLCHAIN,
            visibility=SkillVisibility.BOTH,
            default_agent=AgentRole.RETRIEVER,
            output_artifact_type="rag_result",
            backend_ref="mcp:academic.search.bundle",
        ),
        SkillManifest(
            skill_id="paper_plan_builder",
            name="Paper Plan Builder",
            description="Generate section outline from cards and matrix",
            backend=SkillBackend.LOCAL_GRAPH,
            visibility=SkillVisibility.BOTH,
            default_agent=AgentRole.ANALYST,
            output_artifact_type="report_outline",
            backend_ref="graph:paper_plan_builder",
        ),
        SkillManifest(
            skill_id="creative_reframe",
            name="Creative Reframe",
            description="Refine topic framing and sub-questions for re-plan",
            backend=SkillBackend.MCP_PROMPT,
            visibility=SkillVisibility.BOTH,
            default_agent=AgentRole.PLANNER,
            output_artifact_type="search_plan",
            backend_ref="prompt:creative_reframe",
        ),
        SkillManifest(
            skill_id="workspace_policy_skill",
            name="Workspace Policy Skill",
            description="Inject workspace-specific constraints and conventions",
            backend=SkillBackend.LOCAL_FUNCTION,
            visibility=SkillVisibility.BOTH,
            default_agent=AgentRole.SUPERVISOR,
            output_artifact_type=None,
            backend_ref="fn:workspace_policy_loader",
        ),
    ])


@router.get("/{skill_id}", response_model=SkillManifest)
async def get_skill(skill_id: str):
    # TODO: lookup registry
    raise NotImplementedError


@router.post("/run", response_model=SkillRunResponse)
async def run_skill(req: SkillRunRequest):
    # TODO: resolve backend from registry, run via skill runtime
    raise NotImplementedError
```

### 这组接口干什么

给前端的 **Skill Palette** 用。
用户可以显式点技能，而不是只依赖 agent 自己决定。

---

# 4）`src/api/routes/mcp.py`

```python
from pydantic import BaseModel, Field, ConfigDict

from src.models.mcp import (
    MCPServerConfig,
    MCPToolDescriptor,
    MCPPromptDescriptor,
    MCPResourceDescriptor,
    MCPInvocationRequest,
    MCPInvocationResponse,
)


class ListServersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MCPServerConfig] = Field(default_factory=list)


class MCPCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[MCPToolDescriptor] = Field(default_factory=list)
    prompts: list[MCPPromptDescriptor] = Field(default_factory=list)
    resources: list[MCPResourceDescriptor] = Field(default_factory=list)
```

```python
from fastapi import APIRouter

from src.api.routes.mcp_schemas import ListServersResponse, MCPCatalogResponse
from src.models.mcp import MCPServerConfig, MCPInvocationRequest, MCPInvocationResponse, MCPServerTransport

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@router.get("/servers", response_model=ListServersResponse)
async def list_mcp_servers():
    return ListServersResponse(items=[])


@router.post("/servers", response_model=MCPServerConfig)
async def register_mcp_server(req: MCPServerConfig):
    # TODO: persist server config
    return req


@router.post("/servers/{server_id}/test")
async def test_mcp_server(server_id: str):
    # TODO: adapter health check
    raise NotImplementedError


@router.get("/catalog", response_model=MCPCatalogResponse)
async def get_mcp_catalog(workspace_id: str | None = None):
    # TODO: adapter discovery
    raise NotImplementedError


@router.post("/invoke", response_model=MCPInvocationResponse)
async def invoke_mcp(req: MCPInvocationRequest):
    # TODO: adapter invoke -> trace -> artifact (optional)
    raise NotImplementedError
```

### 这组接口干什么

给前端的 **MCP Catalog / Server Panel** 用。
也就是：

- 查看有哪些 MCP servers
- 能不能连
- 提供哪些 tools/resources/prompts
- 手动执行一次调用

---

## 四、与 Phase 1 的功能映射如何在配置层体现

你前面问过“Phase 4 和 Phase 1 的区别、是否兼容”，现在这层配置就是落地办法。

最关键的就是 `execution_mode + node_backends`。

### 推荐前端默认策略

#### 开发期

```json
{
  "execution_mode": "hybrid",
  "node_backends": {
    "clarify": "legacy",
    "plan_search": "auto",
    "search_corpus": "auto",
    "extract_cards": "auto",
    "review": "auto"
  }
}
```

解释：

- clarify 先不动，符合你 Phase 1 原设计“Clarify 保持固定结构化节点”
- plan/search/extract/review 逐渐 agent 化
- 一旦 v2 backend 失败，自动回退 legacy

#### 内测期

```json
{
  "execution_mode": "v2",
  "enable_mcp": true,
  "enable_skills": true,
  "enable_replan": true
}
```

解释：

- 全走新实现
- 用 trace/eval 做质量对比

#### 回归期

```json
{
  "execution_mode": "legacy"
}
```

解释：

- 一键恢复旧逻辑
- 避免前端和 artifact 展示同时崩

---

## 五、最小服务层协议建议

虽然你这次主要要 schema 和 API，但有一个东西最好一起定下来：
**节点 backend 协议**。

```python
from typing import Protocol

class NodeBackend(Protocol):
    async def run(self, state) -> object:
        ...
```

每个关键节点都可以这样做：

```text
plan_search.py
  ├─ backends/plan_search/legacy.py
  └─ backends/plan_search/v2_agent.py

search_corpus.py
  ├─ backends/search_corpus/legacy.py
  └─ backends/search_corpus/v2_agent.py

extract_cards.py
  ├─ backends/extract_cards/legacy.py
  └─ backends/extract_cards/v2_agent.py

review.py
  ├─ backends/review/legacy.py
  └─ backends/review/v2_agent.py
```

这样你的 graph 节点文件名不变，只是内部按配置选 backend。
这正是“先双轨实现，再删旧逻辑”的最稳路径。

---

## 六、最小 API 闭环

如果现在你想最快把 Phase 4 跑起来，不要一口气做满。
先打通这 8 个接口：

```text
GET  /api/v1/config/phase4
POST /api/v1/config/phase4

GET  /api/v1/agents
POST /api/v1/agents/run
POST /api/v1/agents/replan

GET  /api/v1/skills
POST /api/v1/skills/run

GET  /api/v1/mcp/catalog
POST /api/v1/mcp/invoke
```

这 8 个接口已经足够支撑：

- 前端模式切换
- Agent Switcher
- Skill Palette
- MCP Catalog
- Re-plan
- 手动显式调用

---

## 七、收敛版结论

这版 schema 和 API 的核心不是“把系统彻底改成 multi-agent”，而是：

**在不推翻 Phase 1 控制平面的前提下，把 Phase 4 的 agent、MCP、skills、re-plan 做成可配置、可灰度、可前端显式操控的增强层。**

一句话压缩：

- `config.py` 解决新老逻辑共存
- `agent.py` 解决多角色运行与 re-plan
- `mcp.py` 解决 MCP server/catalog/invoke
- `skills.py` 解决 skills 注册与显式调用
- `agents.py / skills.py / mcp.py / config.py` 四组接口解决前端落地
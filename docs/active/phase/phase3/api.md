可以，下面直接续上 **Phase 3 的 Pydantic schema 设计 + FastAPI 接口草案**。

这版严格围绕你给 Phase 3 定的四件事展开：`ReviewFeedback`、node wrapper + tool trace、workspace artifact 面板、`/internal/evals/run`。同时 reviewer 的职责也保持和你 PRD 一致：检查 coverage gap、unsupported claims、citation reachability、结构重复，并在必要时驱动二轮检索。

---

# 一、推荐落点

```text
src/
  models/
    review.py
    trace.py
    workspace.py
    eval.py

  research/
    services/
      reviewer.py
    graph/
      nodes/
        review.py
        revise.py
        persist_artifacts.py

  tasking/
    trace_wrapper.py
    trace_service.py
    events.py

  api/
    routes/
      tasks.py
      workspaces.py
      evals.py
```

这和你前面的推荐目录是对齐的：`review.py`、`revise.py`、`services/reviewer.py`、`eval/runner.py`、`api/routes/{tasks,workspaces,evals}.py` 都已经在你的整体框架里预留了位置。

---

# 二、Pydantic schema 设计

## 1）`src/models/review.py`

这一层是 reviewer 的正式输出。不要再用松散 dict。

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class ReviewSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class ReviewCategory(str, Enum):
    COVERAGE_GAP = "coverage_gap"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    CITATION_REACHABILITY = "citation_reachability"
    DUPLICATION = "duplication"
    CONSISTENCY = "consistency"


class CoverageGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub_question_id: str | None = None
    missing_topics: list[str] = Field(default_factory=list)
    missing_papers: list[str] = Field(default_factory=list)
    note: str | None = None


class ClaimSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    claim_text: str
    supported: bool
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class RevisionActionType(str, Enum):
    RESEARCH_MORE = "research_more"
    REWRITE_SECTION = "rewrite_section"
    FIX_CITATION = "fix_citation"
    DROP_CLAIM = "drop_claim"
    MERGE_DUPLICATE = "merge_duplicate"


class RevisionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: RevisionActionType
    target: str
    reason: str
    priority: int = 1


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(default_factory=lambda: f"issue_{uuid4().hex[:10]}")
    severity: ReviewSeverity
    category: ReviewCategory
    target: str
    summary: str
    evidence_refs: list[str] = Field(default_factory=list)


class ReviewFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "v1"
    review_id: str = Field(default_factory=lambda: f"review_{uuid4().hex[:12]}")
    task_id: str
    workspace_id: str
    passed: bool
    issues: list[ReviewIssue] = Field(default_factory=list)
    coverage_gaps: list[CoverageGap] = Field(default_factory=list)
    claim_supports: list[ClaimSupport] = Field(default_factory=list)
    revision_actions: list[RevisionAction] = Field(default_factory=list)
    summary: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

这组对象就是你 PRD 里已经明确建议的那四个：`ReviewFeedback`、`CoverageGap`、`ClaimSupport`、`RevisionAction`。

---

## 2）`src/models/trace.py`

这一层给 node wrapper 和 tool trace 用。

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"nr_{uuid4().hex[:12]}")
    task_id: str
    workspace_id: str
    node_name: str
    stage: str
    status: RunStatus = RunStatus.PENDING
    started_at: datetime | None = None
    ended_at: datetime | None = None
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    warning_messages: list[str] = Field(default_factory=list)
    error_message: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_run_id: str = Field(default_factory=lambda: f"tr_{uuid4().hex[:12]}")
    parent_run_id: str
    task_id: str
    workspace_id: str
    node_name: str
    tool_name: str
    status: RunStatus = RunStatus.PENDING
    started_at: datetime | None = None
    ended_at: datetime | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    duration_ms: int | None = None


class TraceEventType(str, Enum):
    TASK_CREATED = "task_created"
    NODE_STARTED = "node_started"
    NODE_FINISHED = "node_finished"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    ARTIFACT_SAVED = "artifact_saved"
    WARNING = "warning"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    task_id: str
    workspace_id: str
    run_id: str | None = None
    tool_run_id: str | None = None
    event_type: TraceEventType
    ts: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
```

你前面 Phase 1 里已经把 SSE 事件类型和 `TaskStatusAPI` 的基本字段列出来了，这里只是把它正式 schema 化，补齐 trace 层。

---

## 3）`src/models/workspace.py`

Phase 1 已经有 workspace / artifact 基础，这里做扩展，不重做。workspace 本来就被你定义成“长期研究工作区”，不是 memory agent。

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class ArtifactType(str, Enum):
    BRIEF = "brief"
    SEARCH_PLAN = "search_plan"
    PAPER_CARD = "paper_card"
    RAG_RESULT = "rag_result"
    COMPARISON_MATRIX = "comparison_matrix"
    REPORT_OUTLINE = "report_outline"
    REPORT_DRAFT = "report_draft"
    REVIEW_FEEDBACK = "review_feedback"
    NODE_TRACE = "node_trace"
    TOOL_TRACE = "tool_trace"
    EVAL_REPORT = "eval_report"
    UPLOAD = "upload"
    TASK_LOG = "task_log"


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: ArtifactType
    title: str


class WorkspaceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(default_factory=lambda: f"art_{uuid4().hex[:12]}")
    workspace_id: str
    task_id: str | None = None
    artifact_type: ArtifactType
    title: str
    status: str = "ready"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by_node: str | None = None
    content_ref: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    status: str
    current_stage: str | None = None
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
```

---

## 4）`src/models/eval.py`

这里给 `/internal/evals/run` 用。Phase 3 的 internal eval 不止 retrieval，还应该支持 reviewer/workflow 级别的评测。你前面的 Phase 3 目标就是把 reviewer 和 trace 做起来，再接上 internal eval。

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class EvalScope(str, Enum):
    RETRIEVAL = "retrieval"
    REVIEWER = "reviewer"
    WORKFLOW = "workflow"


class EvalMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | int | None = None
    note: str | None = None


class EvalCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    scope: EvalScope
    passed: bool
    metrics: list[EvalMetric] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class InternalEvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(default_factory=lambda: f"ieval_{uuid4().hex[:12]}")
    eval_set: str
    scopes: list[EvalScope]
    summary: dict[str, Any] = Field(default_factory=dict)
    case_results: list[EvalCaseResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

---

# 三、FastAPI 接口草案

下面按三类路由来分：

- `tasks.py`：任务状态、trace、review
- `workspaces.py`：artifact 面板
- `evals.py`：internal eval

---

## 1）`src/api/routes/tasks.py`

你前面已经有 task API 和 SSE 方向，这里扩到 trace / review。`TaskStatusAPI` 最少要返回 `status`、`current_stage`、`node_statuses`、`warnings`、`artifacts`，这也是你已有设计。

### schema

```python
from pydantic import BaseModel, Field, ConfigDict

from src.models.trace import NodeRun, ToolRun, TraceEvent
from src.models.review import ReviewFeedback
from src.models.workspace import ArtifactRef


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    workspace_id: str
    status: str
    current_stage: str | None = None
    node_statuses: list[NodeRun] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)


class TaskTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    node_runs: list[NodeRun] = Field(default_factory=list)
    tool_runs: list[ToolRun] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)


class TaskReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    review: ReviewFeedback | None = None
```

### 路由

```python
from fastapi import APIRouter, HTTPException

from src.api.routes.task_schemas import (
    TaskStatusResponse,
    TaskTraceResponse,
    TaskReviewResponse,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    # TODO: query task manager + workspace service
    raise NotImplementedError


@router.get("/{task_id}/trace", response_model=TaskTraceResponse)
async def get_task_trace(task_id: str):
    # TODO: load node runs, tool runs, events
    raise NotImplementedError


@router.get("/{task_id}/review", response_model=TaskReviewResponse)
async def get_task_review(task_id: str):
    # TODO: fetch latest review_feedback artifact
    raise NotImplementedError


@router.get("/{task_id}/events")
async def stream_task_events(task_id: str):
    # TODO: existing SSE stream, now backed by TraceEvent
    raise NotImplementedError
```

---

## 2）`src/api/routes/workspaces.py`

这一层就是 workspace artifact 面板的数据接口。你前面已经把 `GET /api/v1/workspaces/{workspace_id}/artifacts` 放进 API 设计里。

### schema

```python
from pydantic import BaseModel, Field, ConfigDict

from src.models.workspace import WorkspaceArtifact, WorkspaceSummary


class WorkspaceArtifactsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    items: list[WorkspaceArtifact] = Field(default_factory=list)
```

### 路由

```python
from fastapi import APIRouter

from src.api.routes.workspace_schemas import (
    WorkspaceArtifactsResponse,
)
from src.models.workspace import WorkspaceSummary

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


@router.get("/{workspace_id}", response_model=WorkspaceSummary)
async def get_workspace(workspace_id: str):
    # TODO: workspace summary
    raise NotImplementedError


@router.get("/{workspace_id}/artifacts", response_model=WorkspaceArtifactsResponse)
async def list_workspace_artifacts(workspace_id: str):
    # TODO: artifact repository query
    raise NotImplementedError
```

### 这个面板最小应该能展示什么

先别搞复杂，最少四块：

- 当前 task / stage
- artifact 列表
- review summary
- trace timeline

因为你现在最缺的是“真实可追踪”，不是 UI 炫技。PRD 里也已经强调系统特征是“长流程、可中断、可恢复、可追踪、可复用”。

---

## 3）`src/api/routes/evals.py`

这里给 internal eval。Phase 3 的这个接口本质上是内部质量回归，不是给普通用户的业务接口。

### schema

```python
from pydantic import BaseModel, Field, ConfigDict

from src.models.eval import EvalScope, InternalEvalReport


class InternalEvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eval_set: str
    scopes: list[EvalScope] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    include_trace: bool = True
    include_review: bool = True
    include_artifacts: bool = True


class InternalEvalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: InternalEvalReport
```

### 路由

```python
from fastapi import APIRouter

from src.api.routes.eval_schemas import InternalEvalRequest, InternalEvalResponse

router = APIRouter(prefix="/internal/evals", tags=["internal-evals"])


@router.post("/run", response_model=InternalEvalResponse)
async def run_internal_evals(req: InternalEvalRequest):
    # TODO:
    # 1. load tasks / workspace artifacts / traces
    # 2. run retrieval / reviewer / workflow metrics
    # 3. build InternalEvalReport
    raise NotImplementedError
```

这就是你 Phase 3 明确写出来的 `/internal/evals/run`。

---

# 四、trace wrapper 设计草案

这一层不属于 FastAPI 路由，但 Phase 3 里必须一起定下来，不然 `NodeRun` / `ToolRun` 只是空 schema。

## `src/tasking/trace_wrapper.py`

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from functools import wraps

from src.models.trace import NodeRun, ToolRun, RunStatus


def trace_node(node_name: str, stage: str):
    def decorator(fn):
        @wraps(fn)
        async def wrapper(state, *args, **kwargs):
            run = NodeRun(
                task_id=state.task_id,
                workspace_id=state.workspace_id,
                node_name=node_name,
                stage=stage,
                status=RunStatus.RUNNING,
                started_at=datetime.utcnow(),
            )
            # TODO: persist run + emit node_started
            try:
                result = await fn(state, *args, **kwargs)
                run.status = RunStatus.SUCCEEDED
                return result
            except Exception as e:
                run.status = RunStatus.FAILED
                run.error_message = str(e)
                raise
            finally:
                run.ended_at = datetime.utcnow()
                # TODO: compute duration + persist + emit node_finished
        return wrapper
    return decorator


def trace_tool(tool_name: str):
    def decorator(fn):
        @wraps(fn)
        async def wrapper(context, *args, **kwargs):
            tool_run = ToolRun(
                parent_run_id=context.parent_run_id,
                task_id=context.task_id,
                workspace_id=context.workspace_id,
                node_name=context.node_name,
                tool_name=tool_name,
                status=RunStatus.RUNNING,
                started_at=datetime.utcnow(),
            )
            # TODO: persist + emit tool_started
            try:
                result = await fn(context, *args, **kwargs)
                tool_run.status = RunStatus.SUCCEEDED
                return result
            except Exception as e:
                tool_run.status = RunStatus.FAILED
                tool_run.error_message = str(e)
                raise
            finally:
                tool_run.ended_at = datetime.utcnow()
                # TODO: duration + persist + emit tool_finished
        return wrapper
    return decorator
```

### 怎么接到 graph 里

例如：

```python
@trace_node(node_name="review", stage="review")
async def review_node(state: ResearchState) -> ResearchState:
    ...
```

和：

```python
@trace_tool(tool_name="rag_search")
async def run_rag_search(context, query: str):
    ...
```

这样 trace 就不会散到每个节点内部去。

---

# 五、Reviewer service 草案

## `src/research/services/reviewer.py`

```python
from __future__ import annotations

from src.models.review import (
    ReviewFeedback,
    ReviewIssue,
    ReviewCategory,
    ReviewSeverity,
    CoverageGap,
    ClaimSupport,
    RevisionAction,
    RevisionActionType,
)


class ReviewerService:
    async def review(
        self,
        *,
        task_id: str,
        workspace_id: str,
        rag_result,
        paper_cards,
        report_draft,
    ) -> ReviewFeedback:
        issues: list[ReviewIssue] = []
        coverage_gaps: list[CoverageGap] = []
        claim_supports: list[ClaimSupport] = []
        revision_actions: list[RevisionAction] = []

        # TODO: coverage check
        # TODO: unsupported claim check
        # TODO: citation reachability check
        # TODO: duplication / consistency check

        passed = not any(i.severity in {ReviewSeverity.ERROR, ReviewSeverity.BLOCKER} for i in issues)

        return ReviewFeedback(
            task_id=task_id,
            workspace_id=workspace_id,
            passed=passed,
            issues=issues,
            coverage_gaps=coverage_gaps,
            claim_supports=claim_supports,
            revision_actions=revision_actions,
            summary="auto-generated review summary",
        )
```

这层的业务逻辑就正是你 PRD 里 reviewer 的职责集合。

---

# 六、PersistArtifacts 节点要怎么扩

你前面的 `PersistArtifacts` 已经定义得很清楚：写入 workspace、生成 artifact refs、更新 task 状态、触发 SSE。Phase 3 不要重做，只要把 artifact 类型扩展到 reviewer / trace / eval。

也就是除了原有：

- `brief`
- `search_plan`
- `paper_card`
- `upload`
- `task_log`

再新增：

- `rag_result`
- `comparison_matrix`
- `report_draft`
- `review_feedback`
- `node_trace`
- `tool_trace`
- `eval_report`

---

# 七、最小 API 闭环

如果你现在要先做一个最小可运行的 Phase 3，不要一次把所有 fancy 功能都堆进去。先打通这 6 个接口就够：

```text
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/trace
GET  /api/v1/tasks/{task_id}/review
GET  /api/v1/tasks/{task_id}/events
GET  /api/v1/workspaces/{workspace_id}/artifacts
POST /internal/evals/run
```

这 6 个接口正好覆盖：

- 状态
- trace
- review
- SSE
- artifact 面板
- internal eval

---

# 八、实现顺序建议

按最稳的顺序来：

### 第一步

先把 schema 定稳：

- `review.py`
- `trace.py`
- `workspace.py`
- `eval.py`

### 第二步

给现有节点加 `@trace_node`，给工具运行时加 `@trace_tool`

### 第三步

把 `review.py` 节点接到 graph，先输出 `ReviewFeedback`

### 第四步

扩 `PersistArtifacts`，把 review/trace/eval 都写进 workspace

### 第五步

补 6 个 API

### 第六步

最后再做 `/internal/evals/run` 的 metrics 聚合

这样不会把 Phase 3 做成一团乱麻，也符合你原来的 phase 顺序：先补 `Trace -> Eval` 这些基础设施链路，再往后谈更强的 multi-agent / MCP。

---
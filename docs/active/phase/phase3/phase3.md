### Phase 3：把 reviewer 和 trace 做起来

要做：

- `ReviewFeedback`
- node wrapper + tool trace
- workspace artifact 面板
- `/internal/evals/run`

---

可以，Phase 3 该做的不是再加新能力点，而是把 **质量控制链路** 补齐：让系统不仅“能检索、能抽取、能写”，还要“能审、能追、能展示、能评测”。你前面的规划已经把这一阶段收得很清楚：核心就是 `ReviewFeedback`、node wrapper + tool trace、workspace artifact 面板，以及 `/internal/evals/run`；而且这一步的优先级本来就高于更强的 multi-agent / MCP，因为基础设施主线应先补齐 `Tool Runtime -> Trace -> Eval -> RAG`。

---

## 一、Phase 3 的目标重定义

Phase 1 解决“任务能跑”。
Phase 2 解决“检索能用”。
Phase 3 解决“结果能不能被信任”。

所以这一阶段的正式定义应该是：

**把 reviewer、trace、artifact、eval 组装成一个可审计的质量闭环。**

也就是从：

```text
search → extract → synthesize
```

升级成：

```text
search → extract → synthesize → review → revise → persist → eval
```

这里 reviewer 不是新造概念。你 PRD 已经明确说了，当前 demo 已经有 citation resolve、source tier、reachability、claim judge、policy 汇总，所以 reviewer 不是从零开始，而是把现有强项抬升成 research workflow 的正式阶段；它的职责就是检查 coverage gap、unsupported claims、citation reachability、结构重复，生成 `ReviewFeedback`，必要时触发二轮检索。

---

## 二、Phase 3 的整体架构

这一阶段建议收成四个模块：

```text
Phase 3 Quality Loop
├─ Reviewer / Grounding
├─ Execution Trace
├─ Workspace Artifact Panel
└─ Internal Eval Runner
```

这四块不是并列孤岛，而是一条链：

```text
graph nodes / tools
      ↓
node wrapper + tool trace
      ↓
reviewer reads structured artifacts
      ↓
generate ReviewFeedback / RevisionAction
      ↓
persist to workspace artifacts
      ↓
run /internal/evals/run
```

---

## 三、模块 1：Reviewer / Grounding / Verification

### 1. 定位

Reviewer 是 **质量闸门**，不是生成器，也不是 planner。
它吃的输入不该是原始自由文本，而应该是前面 Phase 2 已经产出的中间结构，比如 `PaperCard`、`ComparisonMatrix`、`ReportOutline`、`ReportDraft`、`RagResult`。你 PRD 里也强调过，综述模块最好先产出中间结构，让 reviewer 来审查，而不是直接跳到 final report。

### 2. 输入

建议 reviewer 读取这些对象：

- `ResearchBrief`
- `SearchPlan`
- `RagResult`
- `PaperCard[]`
- `ComparisonMatrix`
- `ReportOutline`
- `ReportDraft`

### 3. 核心职责

沿用你 PRD 里已经定义好的四类检查，再扩成明确的检查面：

#### 覆盖性检查

- query / sub-question 是否都被覆盖
- 是否缺失关键论文
- 是否某个 section 没有足够证据

#### claim 支撑检查

- 报告里的 claim 是否有 evidence span
- 是否存在 unsupported claims
- evidence 是否来自正确 paper/chunk

#### citation 可达性检查

- citation 是否能回指到 source
- source 是否仍然可访问
- citation 是否绑到了正确的 canonical paper

#### 结构质量检查

- section 重复
- 论点重复
- taxonomy / matrix / draft 是否一致

这些正是你 PRD 对 reviewer 的既定职责。

### 4. 输出对象

建议对象还是按你原文来定：

- `ReviewFeedback`
- `CoverageGap`
- `ClaimSupport`
- `RevisionAction`

其中 `ReviewFeedback` 作为顶层对象，下面挂具体问题。

### 5. 推荐 schema

```python
class ReviewSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class CoverageGap(BaseModel):
    sub_question_id: str | None = None
    missing_topics: list[str] = []
    missing_papers: list[str] = []
    note: str | None = None


class ClaimSupport(BaseModel):
    claim_id: str
    claim_text: str
    supported: bool
    evidence_chunk_ids: list[str] = []
    citation_ids: list[str] = []
    note: str | None = None


class RevisionActionType(str, Enum):
    RESEARCH_MORE = "research_more"
    REWRITE_SECTION = "rewrite_section"
    FIX_CITATION = "fix_citation"
    DROP_CLAIM = "drop_claim"
    MERGE_DUPLICATE = "merge_duplicate"


class RevisionAction(BaseModel):
    action_type: RevisionActionType
    target: str
    reason: str
    priority: int = 1


class ReviewIssue(BaseModel):
    issue_id: str
    severity: ReviewSeverity
    category: Literal[
        "coverage_gap",
        "unsupported_claim",
        "citation_reachability",
        "duplication",
        "consistency",
    ]
    target: str
    summary: str
    evidence_refs: list[str] = []


class ReviewFeedback(BaseModel):
    review_id: str
    task_id: str
    workspace_id: str
    passed: bool
    issues: list[ReviewIssue] = []
    coverage_gaps: list[CoverageGap] = []
    claim_supports: list[ClaimSupport] = []
    revision_actions: list[RevisionAction] = []
    summary: str | None = None
```

### 6. graph 集成方式

建议新增两个节点，而不是一个 review 节点包打天下：

- `review.py`：生成 `ReviewFeedback`
- `revise.py`：根据 `RevisionAction` 选择局部修订或二轮检索

这和你原来推荐的 graph 节点列表其实是对齐的，里面本来就有 `review.py` 和 `revise.py`。

### 7. reviewer 的流图

```text
RagResult + PaperCards + Draft
          ↓
     Reviewer
          ↓
┌───────────────────────────────┐
│ coverage check                │
│ unsupported claim check       │
│ citation reachability check   │
│ duplication / consistency     │
└───────────────────────────────┘
          ↓
    ReviewFeedback
          ↓
  pass / partial / fail
          ↓
 revise or persist
```

---

## 四、模块 2：Node Wrapper + Tool Trace

这是 Phase 3 最容易被低估、但其实最关键的一块。

### 1. 为什么要做 wrapper

你 PRD 已经把问题讲得很明白：当前工具层其实偏弱，很多新图节点还是直接 import 函数，tool schema 也还占位；而且现在虽然有 SSE，但 `NodeStatus`/trace 还没有真正接线。换句话说，现在系统“在跑”，但不够“可追踪”。

所以 Phase 3 不该只加 reviewer，而是要让每个 node、每次 tool call 都被包装、记录、关联到 task/workspace/artifact。

### 2. 设计原则

#### wrapper 包 node，不改 node 内核

不要把 trace 逻辑散落到每个节点里。
应该由统一 decorator / wrapper 在入口和出口记录。

#### tool trace 和 node trace 分开

因为一个 node 内部可能调多个 tool。
两层 trace 要分开建模，但通过 correlation id 关联。

#### trace 是 artifact，不只是 log

以后 workspace 面板和 eval 都要看，所以 trace 不能只是 print 或 console log。

### 3. 建议对象

#### NodeRun

记录一次节点执行。

#### ToolRun

记录一次工具调用。

#### Event / Span

记录流式阶段事件。

### 4. 推荐 schema

```python
class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeRun(BaseModel):
    run_id: str
    task_id: str
    workspace_id: str
    node_name: str
    stage: str
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None = None
    input_artifact_ids: list[str] = []
    output_artifact_ids: list[str] = []
    warning_messages: list[str] = []
    error_message: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = {}


class ToolRun(BaseModel):
    tool_run_id: str
    parent_run_id: str
    task_id: str
    workspace_id: str
    node_name: str
    tool_name: str
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None = None
    input_summary: dict[str, Any] = {}
    output_summary: dict[str, Any] = {}
    error_message: str | None = None
    duration_ms: int | None = None


class TraceEvent(BaseModel):
    event_id: str
    task_id: str
    run_id: str | None = None
    tool_run_id: str | None = None
    event_type: str
    ts: datetime
    payload: dict[str, Any] = {}
```

### 5. 推荐 wrapper 形式

#### `@trace_node`

包装 graph node 执行。

#### `@trace_tool`

包装 tool runtime 执行。

### 6. 最小执行时序

```text
graph enters node
   ↓
create NodeRun(status=running)
   ↓
node body executes
   ↓
tool call → create ToolRun(status=running)
   ↓
tool returns / fails
   ↓
update ToolRun
   ↓
node returns artifact refs
   ↓
update NodeRun(status=succeeded/failed)
   ↓
emit SSE + persist trace artifact
```

### 7. 文件建议

```text
src/
  tasking/
    trace_models.py
    trace_wrapper.py
    trace_service.py
  tools/
    runtime.py
```

其中：

- `trace_wrapper.py`：decorator / context manager
- `trace_service.py`：持久化与 SSE 派发
- `tools/runtime.py`：统一入口打 `@trace_tool`

---

## 五、模块 3：Workspace Artifact 面板

这一块本质上是把“研究产物”和“执行轨迹”放在一个长期工作区里展示出来。

你前面已经把 workspace 定位为长期研究工作区，而不是 memory agent；同时 Phase 1 其实就已经有 artifact 基础，包括 `brief`、`search_plan`、`paper_card`、`upload`、`task_log` 等类型。Phase 3 应该在这个基础上扩，不是重做。

### 1. 面板目标

用户不是只看最终报告，还要能看到：

- 当前 task 跑到哪一步
- 每个节点的状态
- 生成了哪些中间产物
- reviewer 提了哪些问题
- 哪些 citation / claims 有风险
- eval 结果如何

### 2. artifact 类型扩展

建议在原先 artifact 类型基础上新增：

- `rag_result`
- `comparison_matrix`
- `report_outline`
- `report_draft`
- `review_feedback`
- `node_trace`
- `tool_trace`
- `eval_report`

### 3. WorkspaceArtifact schema

```python
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
    TASK_LOG = "task_log"
    UPLOAD = "upload"


class WorkspaceArtifact(BaseModel):
    artifact_id: str
    workspace_id: str
    task_id: str | None = None
    artifact_type: ArtifactType
    title: str
    status: str = "ready"
    created_at: datetime
    created_by_node: str | None = None
    content_ref: str | None = None
    summary: str | None = None
    tags: list[str] = []
    metadata: dict[str, Any] = {}
```

### 4. 面板最小视图

建议 UI 先做四栏，不用一开始很花：

#### 左栏：Task / Stage

- task status
- current stage
- latest warnings

#### 中栏：Artifacts

- brief
- search\_plan
- paper\_cards
- draft
- review\_feedback
- eval\_report

#### 右栏：Trace

- node timeline
- tool timeline
- failed calls

#### 底栏：Review Summary

- blocker / warning 数量
- unsupported claims
- coverage gaps
- citation reachability problems

### 5. 最小 API

```text
GET  /api/v1/workspaces/{workspace_id}
GET  /api/v1/workspaces/{workspace_id}/artifacts
GET  /api/v1/tasks/{task_id}/trace
GET  /api/v1/tasks/{task_id}/review
GET  /api/v1/tasks/{task_id}/evals
```

---

## 六、模块 4：`/internal/evals/run`

这个接口在 Phase 3 里非常关键，因为它把 trace、artifact、reviewer 串成可验证的工程闭环。

### 1. 定位

不是给最终用户的业务 API，
而是给内部回归测试、冒烟测试、策略对比、节点质量检查用的。

### 2. 为什么放到 Phase 3

因为只有到这一步，你才有：

- `RagResult`
- `ReviewFeedback`
- node trace
- tool trace
- workspace artifacts

也就是说，现在评测的不只是 retrieval，而是整个 workflow quality loop。

### 3. eval 范围

建议 `/internal/evals/run` 同时支持三类 eval：

#### A. Retrieval Eval

沿用你 Phase 2 的 RAG eval，测：

- Recall@K
- nDCG
- evidence recall
- citation reachability rate

#### B. Reviewer Eval

测 reviewer 自身：

- coverage gap 检出率
- unsupported claim 检出率
- citation problem 检出率
- false positive rate

#### C. Workflow Eval

测系统整体：

- task success rate
- stage completion rate
- average retries
- node failure distribution
- artifact completeness
- review pass rate

### 4. 请求 schema

```python
class EvalScope(str, Enum):
    RETRIEVAL = "retrieval"
    REVIEWER = "reviewer"
    WORKFLOW = "workflow"


class InternalEvalRequest(BaseModel):
    eval_set: str
    scopes: list[EvalScope] = []
    task_ids: list[str] = []
    workspace_id: str | None = None
    include_trace: bool = True
    include_review: bool = True
    include_artifacts: bool = True


class InternalEvalReport(BaseModel):
    report_id: str
    eval_set: str
    scopes: list[EvalScope]
    summary: dict[str, Any]
    case_results: list[dict[str, Any]]
    created_at: datetime
```

### 5. 路由草案

```python
@router.post("/internal/evals/run", response_model=InternalEvalReport)
async def run_internal_evals(req: InternalEvalRequest):
    # 1. load cases / tasks
    # 2. replay or inspect artifacts
    # 3. run retrieval/reviewer/workflow metrics
    # 4. return aggregated report
    ...
```

### 6. 最小指标集合

如果你想先控成本，先做这几个就够：

- `retrieval_recall_at_k`
- `evidence_recall_at_k`
- `citation_reachability_rate`
- `unsupported_claim_detection_rate`
- `coverage_gap_detection_rate`
- `node_success_rate`
- `artifact_completeness_rate`
- `review_pass_rate`

---

## 七、Phase 3 的 graph 集成方式

建议把 graph 从：

```text
clarify → plan_search → search_corpus → extract_cards → synthesize → write_final
```

升级成：

```text
clarify
  → plan_search
  → search_corpus
  → select_papers
  → extract_cards
  → synthesize_matrix
  → write_report
  → review
  → revise? 
  → persist_artifacts
```

其中：

- 所有 node 都通过 `@trace_node`
- node 内工具调用都通过 `@trace_tool`
- `review` 节点生成 `ReviewFeedback`
- `revise` 节点根据 `RevisionAction` 决定是局部改写还是二轮检索
- `persist_artifacts` 把 reviewer / trace / eval 结果都写进 workspace

你之前给的建议节点里本来就有 `review.py`、`revise.py`、`write_report.py` 这几块，所以这一步是顺延，不是推翻。

---

## 八、推荐目录结构

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
    trace_service.py
    trace_wrapper.py

  api/
    routes/
      workspaces.py
      evals.py
      tasks.py

  eval/
    runner.py
    cases/
    gates/
```

这和你原始推荐目录里的 `services/reviewer.py`、`graph/nodes/review.py`、`revise.py`、`eval/runner.py cases/ gates/` 是一脉相承的。

---

## 九、Phase 3 的端到端流图

### 1. 总体流图

```text
Search / Extraction / Synthesis
            ↓
        write_report
            ↓
         review.py
            ↓
     ReviewFeedback artifact
            ↓
   ┌────────┴────────┐
   │                 │
 pass             needs_revision
   │                 │
 persist         revise.py
   │                 │
 workspace       partial re-search / rewrite
   │                 │
   └────────┬────────┘
            ↓
     persist_artifacts
            ↓
  node_trace + tool_trace + review_feedback
            ↓
    /internal/evals/run
```

### 2. trace 流图

```text
Node starts
   ↓
create NodeRun
   ↓
Tool starts
   ↓
create ToolRun
   ↓
Tool ends
   ↓
update ToolRun
   ↓
Node ends
   ↓
update NodeRun
   ↓
emit SSE + save artifacts
```

### 3. workspace 面板视图流图

```text
Task
 ├─ current stage
 ├─ node statuses
 ├─ warnings
 ├─ review summary
 ├─ artifacts list
 └─ trace timeline
```

---

## 十、交付物定义

Phase 3 做完，至少应该明确交付这些东西：

### reviewer

- `ReviewFeedback` schema
- `CoverageGap / ClaimSupport / RevisionAction`
- `review.py`
- `revise.py`

### trace

- `NodeRun / ToolRun / TraceEvent`
- `@trace_node`
- `@trace_tool`
- trace persistence + SSE hook

### workspace

- artifact model 扩展
- artifact panel API
- review / trace artifact 展示

### eval

- `/internal/evals/run`
- reviewer/workflow eval metrics
- eval report artifact

---

## 十一、最收敛的结论

Phase 3 不该理解成“再加一个 reviewer 节点”，而是：

**把系统从能生成内容，升级成能审计内容。**

一句话压缩：

- `ReviewFeedback` 负责指出哪里不可信
- `node wrapper + tool trace` 负责说明系统怎么走到这个结果
- `workspace artifact 面板` 负责把中间产物和问题展示出来
- `/internal/evals/run` 负责把这条链变成可量化回归测试

---
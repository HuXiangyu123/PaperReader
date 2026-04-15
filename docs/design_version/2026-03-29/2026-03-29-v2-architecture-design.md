# Literature Report Agent v2 — Architecture Design Spec

**Date:** 2026-03-29
**Status:** Draft
**Author:** brainstorming session

---

## 1. Problem Statement

The current agent uses `langgraph.prebuilt.create_react_agent`, a black-box wrapper that prevents:
- Inserting verification/abstention nodes into the execution graph
- Emitting per-node status events for real-time visualization
- Capturing structured per-step traces for regression evaluation

Three launch-blocking capabilities require explicit control over the graph:
1. **Citation verification** with claim-evidence provenance and abstention
2. **Automated regression evaluation** with a three-layer scoring architecture
3. **Task state visualization** via a React frontend connected to FastAPI SSE

## 2. Architecture Overview

### 2.1 Core Change: Migrate to Custom StateGraph

Replace `create_react_agent(llm, tools)` with a hand-built `StateGraph` where every node is named, typed, and individually testable.

### 2.2 Graph Topology

```
input_parse → ingest_source → extract_document_text → normalize_metadata
  → retrieve_evidence → draft_report → repair_report
    → resolve_citations → verify_claims → apply_policy → format_output
```

The first four nodes handle **source ingestion** (symmetric for arXiv and PDF). Downstream nodes receive a canonical `NormalizedDocument` and never need to know the input source type.

Nodes (10 total):

| Node | Input | Output | Tools Used |
|------|-------|--------|------------|
| `input_parse` | Raw user input (arXiv URL/ID or PDF bytes) | `source_type`, `arxiv_id` or raw `pdf_bytes` | `extract_text_from_pdf_bytes` (if PDF) |
| `ingest_source` | `arxiv_id` or `pdf_bytes` | `source_manifest` (origin URL, download path, raw content ref) | arXiv API / HTTP download |
| `extract_document_text` | `source_manifest` | `document_text` (full paper text) | `extract_text_from_pdf_bytes` via downloaded PDF (arXiv) or from uploaded bytes (PDF) |
| `normalize_metadata` | `document_text` + arXiv API result (if available) | `NormalizedDocument(metadata, document_text, document_sections)` | LLM call for PDF-only path to extract title/authors from text |
| `retrieve_evidence` | `NormalizedDocument` | `EvidenceBundle(rag_results[], web_results[])` | `rag_search`, `fetch_webpage_text` (parallel) |
| `draft_report` | `NormalizedDocument` + `EvidenceBundle` | `DraftReport(sections{}, claims[], citations[])` | LLM call with structured output |
| `repair_report` | `DraftReport` | `DraftReport` (repaired) | If missing required sections or citations, LLM retry once; otherwise pass-through. Traces record whether repair was triggered. |
| `resolve_citations` | `DraftReport` | `ResolvedReport` (citations enriched with tier, reachability, fetched content) | HTTP HEAD/GET for reachability; domain regex for tier; fetch content for claim verification |
| `verify_claims` | `ResolvedReport` | `VerifiedReport` (per-claim support matrix populated) | LLM judge: claim-by-citation support assessment |
| `apply_policy` | `VerifiedReport` | `FinalReport` (claim-level abstention markers + report-level degradation) | Rule-based policy engine |
| `format_output` | `FinalReport` | Markdown string with citation list + grounding stats | Pure formatting only; no semantic changes |

**Key structural decisions (from architecture review):**
- **`resolve_citations` split from `verify_claims`** (review Issue #1): citation URL resolution, reachability, content fetching, and tier classification are isolated from claim-evidence judgment. This allows independent retrying, caching, and evaluation of each concern.
- **`repair_report` split from `format_output`** (review Issue #7): structural repair is explicit and traced separately from presentation formatting. The trace clearly shows whether the report needed repair.
- **Symmetric ingestion** (review Issue #3): `ingest_source` → `extract_document_text` → `normalize_metadata` produces the same `NormalizedDocument` regardless of arXiv or PDF input. Downstream nodes never branch on `source_type`.

### 2.3 State Schema

```python
from typing import Annotated
import operator

class NodeStatus(BaseModel):
    node: str
    status: Literal["pending", "running", "done", "limited", "failed", "skipped"]
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    warnings: list[str] = []
    error: str | None = None
    tokens_delta: int = 0
    repair_triggered: bool = False     # True if this node did a retry/repair pass

class NormalizedDocument(BaseModel):
    metadata: PaperMetadata
    document_text: str
    document_sections: dict[str, str]  # heading → content, from PDF structure parsing
    source_manifest: dict              # origin URL, download path, content hash

class AgentState(TypedDict):
    raw_input: str
    source_type: Literal["arxiv", "pdf"]
    arxiv_id: str | None
    pdf_text: str | None
    source_manifest: dict | None
    normalized_doc: NormalizedDocument | None
    evidence: EvidenceBundle | None
    draft_report: DraftReport | None
    resolved_report: ResolvedReport | None
    verified_report: VerifiedReport | None
    final_report: FinalReport | None
    tokens_used: Annotated[int, operator.add]
    warnings: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    degradation_mode: Literal["normal", "limited", "safe_abort"]
    node_statuses: dict[str, NodeStatus]
```

**Design notes:**
- `messages: list[BaseMessage]` is removed from shared state. LLM conversation history is scoped per-node.
- `node_statuses` is a dict keyed by node name; each node writes its own `NodeStatus` on entry/exit. This drives both frontend visualization and eval trace generation.
- `degradation_mode` replaces the old "unconditional continue" policy (see Section 2.4).

### 2.4 Conditional Edges

**Branching:**
- `input_parse` → `ingest_source` → `extract_document_text` → `normalize_metadata` (linear; handles both arXiv and PDF internally based on `source_type`)
- `normalize_metadata` → `retrieve_evidence` → `draft_report` → `repair_report` → `resolve_citations` → `verify_claims` → `apply_policy` → `format_output`

**Degradation policy (replaces unconditional "continue on error"):**

Each node, on completion, may set `degradation_mode`:

| Condition | `degradation_mode` | Behavior |
|-----------|-------------------|----------|
| Node succeeds normally | `normal` | Continue to next node |
| Node partially fails but downstream can still produce useful output | `limited` | Continue, but downstream nodes know to reduce scope (e.g., `draft_report` uses only abstract if `document_text` is missing; `apply_policy` generates a limited-confidence report header) |
| Critical data is absent (both metadata and text missing; or `draft_report` produced empty output) | `safe_abort` | Skip remaining nodes; `format_output` emits a minimal error summary instead of a fake report |

**Specific degradation rules:**
- `ingest_source` fails for arXiv but PDF text exists → `limited`
- `extract_document_text` fails but metadata.abstract exists → `limited`
- Both metadata and text are absent → `safe_abort`
- `resolve_citations` has zero usable citation content → `limited` (report proceeds but `apply_policy` will emit a low-confidence warning)
- `verify_claims` cannot judge any claims (e.g., all citation content unfetchable) → `limited`

**Per-node timeouts:** LLM calls default 120s; HTTP fetches 30s; overall graph execution 300s. Exceeded timeout → node status `failed`, evaluate degradation rule above.

---

## 3. Citation Verification System

### 3.1 Source Tier Classification

| Tier | Domains / Patterns | Trust Level | Examples |
|------|---------------------|-------------|----------|
| Tier A | Paper itself, DOI landing page, publisher page, OpenReview, arXiv paper page | Authoritative | `arxiv.org/abs/...`, `doi.org/...`, `openreview.net`, ACM/IEEE/Springer/Nature/Science |
| Tier B | Official documentation, official benchmarks, official model cards, institutional pages | Official | `docs.python.org`, `huggingface.co/docs`, university `.edu` pages |
| Tier C | Code repositories, demos, issue trackers | Implementation | `github.com/<org>/<repo>`, `gitlab.com`, `colab.research.google.com` |
| Tier D | Blog posts, wikis, forums, unknown domains | Community | Medium, personal blogs, Stack Overflow, Wikipedia |

Classification: URL domain regex matching, stored as a configurable YAML/JSON map.

**Rationale (review Issue #6):** The original 3-tier system put GitHub repos alongside arXiv/DOI, which conflates code availability with scholarly authority. A code repo is useful but is not the same trust signal as a published paper or DOI.

### 3.2 Claim-Evidence Provenance

Each claim in the generated report must be structured as:

All domain models use Pydantic `BaseModel` (not `@dataclass`) for JSON serialization, validation, and FastAPI integration. `TypedDict` is reserved for `AgentState` (LangGraph requirement).

All domain models use Pydantic `BaseModel`. `TypedDict` is reserved for `AgentState` (LangGraph requirement).

```python
class PaperMetadata(BaseModel):
    title: str
    authors: list[str]
    abstract: str
    pdf_url: str | None = None
    published: str | None = None

class RagResult(BaseModel):
    text: str
    doc_id: str
    score: float

class WebResult(BaseModel):
    url: str
    text: str
    status_code: int

class EvidenceBundle(BaseModel):
    rag_results: list[RagResult]
    web_results: list[WebResult]

class Citation(BaseModel):
    label: str                        # e.g. "[1]"
    url: str
    reason: str
    source_tier: Literal["A", "B", "C", "D"] | None = None  # Populated by resolve_citations
    reachable: bool | None = None                             # Populated by resolve_citations
    fetched_content: str | None = None                        # Snippet fetched for claim verification

class ClaimSupport(BaseModel):
    """Per-citation support assessment for a single claim."""
    claim_id: str
    citation_label: str
    support_status: Literal["supported", "partial", "unsupported", "unverifiable"]
    evidence_excerpt: str | None = None
    reason: str | None = None
    judge_confidence: float | None = None   # 0.0–1.0

class Claim(BaseModel):
    id: str
    text: str
    citation_labels: list[str]
    supports: list[ClaimSupport] = []       # Populated by verify_claims; one entry per citation
    overall_status: Literal["grounded", "partial", "ungrounded", "abstained"] = "ungrounded"
    # overall_status is derived from supports: grounded if any supported, partial if any partial, etc.

class GroundingStats(BaseModel):
    total_claims: int
    grounded: int
    partial: int
    ungrounded: int
    abstained: int
    tier_a_ratio: float
    tier_b_ratio: float

class DraftReport(BaseModel):
    sections: dict[str, str]          # heading → content
    claims: list[Claim]
    citations: list[Citation]

class ResolvedReport(BaseModel):
    """DraftReport with citations enriched by resolve_citations node."""
    sections: dict[str, str]
    claims: list[Claim]
    citations: list[Citation]         # source_tier + reachable + fetched_content populated

class VerifiedReport(BaseModel):
    sections: dict[str, str]
    claims: list[Claim]               # supports[] populated per claim
    citations: list[Citation]

class FinalReport(BaseModel):
    sections: dict[str, str]
    claims: list[Claim]               # overall_status finalized; abstention markers in text
    citations: list[Citation]
    grounding_stats: GroundingStats
    report_confidence: Literal["high", "limited", "low"]  # Derived from grounding ratio
```

**Claim support matrix (review Issue #4):** A single claim may cite multiple sources; each (claim, citation) pair gets its own `ClaimSupport` with independent `support_status` and `evidence_excerpt`. The claim's `overall_status` is derived from its supports (e.g., grounded if ≥1 supported, partial if best is partial, ungrounded if all unsupported/unverifiable).

The existing `src/retrieval/citations.py` `Citation` dataclass is superseded by the Pydantic `Citation` model above; the old module will be removed during Phase 1 migration.
The existing `src/validators/citations_validator.py` `has_citations_section()` is absorbed into `repair_report` node and Layer 1 eval checks; the old module will be removed.

**Resolution process (in `resolve_citations` node):**
1. Normalize citation URLs (strip tracking params, resolve DOI redirects)
2. Reachability check: HTTP HEAD first; fallback GET with 5s timeout + 1KB byte limit if HEAD fails; cache results by normalized URL
3. Classify source tier (A/B/C/D) by domain regex
4. Fetch citation content snippet (up to 2000 chars around relevant section) for use by `verify_claims`

**Verification process (in `verify_claims` node):**
1. For each (claim, citation) pair where `fetched_content` is available:
2. LLM judge prompt: "Does the source contain information that supports this claim? Quote the relevant passage and explain."
3. Outputs one `ClaimSupport` per pair with `support_status` + `evidence_excerpt` + `reason`
4. Claim `overall_status` derived: if any support is `supported` → `grounded`; if best is `partial` → `partial`; if all `unsupported`/`unverifiable` → `ungrounded`

### 3.3 Policy Engine (in `apply_policy` node)

**Claim-level policy:**
- `overall_status == "ungrounded"` → marker: `「⚠️ 未找到充分证据支撑」`
- `overall_status == "partial"` → marker: `「⚡ 部分证据支撑，需进一步核实」`

**Report-level policy (review Issue #2 — prevents polished reports with mostly soft warnings):**

| Grounding Ratio | `report_confidence` | Report Behavior |
|-----------------|---------------------|-----------------|
| ≥ 80% grounded | `high` | Normal full report |
| 50%–79% grounded | `limited` | Full report with prominent limited-confidence header |
| < 50% grounded or no citation evidence fetched | `low` | Minimal safe summary only; full report suppressed |

Report summary includes a grounding statistics block:
  ```
  ## 引用可信度
  - Grounded: 12/15 (80%)
  - Partial: 2/15 (13%)
  - Abstained: 1/15 (7%)
  - Tier A 来源占比: 47%
  - Tier B 来源占比: 20%
  - 报告置信度: high
  ```

### 3.4 URL Reachability

- HTTP HEAD first (timeout 5s); fallback GET with 5s timeout + 1KB byte limit if HEAD returns 4xx/5xx or times out
- Cache result by normalized URL (in-memory for single run; prevents duplicate fetches)
- Unreachable URLs marked with `「🔗 链接不可达」`
- Run as async batch in `resolve_citations` node

---

## 4. Evaluation Pipeline

### 4.1 Eval Set: 20 Cases

| Task Type | Count | Notes |
|-----------|-------|-------|
| Single paper (arXiv URL) | 8 | CS×2, Bio×2, Physics×2, Math×2; includes 1 long paper (>30 pages) |
| Single paper (PDF upload) | 4 | 1 scanned PDF (expect graceful fail), 1 non-English |
| Sequential multi-paper (loop) | 3 | Run the single-paper pipeline 2–3 times and concatenate; no cross-paper synthesis in v2 |
| Claim-evidence gold | 3 | Pre-annotated claims with known grounding status |
| Boundary/error | 2 | Non-existent arXiv ID, unreachable URL |

Cases stored in `eval/cases.jsonl`. Standard case:
```json
{
  "id": "cs-transformer-01",
  "task_type": "single_arxiv",
  "input": {"arxiv_url_or_id": "1706.03762"},
  "expected_sections": ["标题", "核心贡献", "方法概述", "关键实验", "局限性", "引用"],
  "expected_min_citations": 3,
  "expected_min_tier1_ratio": 0.5,
  "known_claims": null
}
```

Gold claim-evidence case (for the 3 specialized eval cases):
```json
{
  "id": "gold-claim-attention-01",
  "task_type": "claim_evidence_gold",
  "input": {"arxiv_url_or_id": "1706.03762"},
  "expected_sections": ["标题", "核心贡献", "方法概述", "关键实验", "局限性", "引用"],
  "expected_min_citations": 3,
  "expected_min_tier1_ratio": 0.5,
  "known_claims": [
    {
      "text": "Transformer 完全摒弃了循环和卷积结构，仅依赖注意力机制",
      "expected_grounding": "grounded",
      "source_excerpt": "dispensing with recurrence and convolutions entirely",
      "source_url": "https://arxiv.org/abs/1706.03762"
    },
    {
      "text": "Transformer 在 WMT 2014 英德翻译任务上达到 28.4 BLEU",
      "expected_grounding": "grounded",
      "source_excerpt": "28.4 BLEU on the WMT 2014 English-to-German translation task",
      "source_url": "https://arxiv.org/abs/1706.03762"
    }
  ]
}
```

### 4.2 Three-Layer Scoring

**Layer 1: Hard-Rule Checks (zero-cost, code assertions)**

| Check | Method | Pass Condition |
|-------|--------|----------------|
| Structure completeness | Regex match required headings | All present |
| Citation format | Each citation has label + url + reason | 100% |
| URL reachability | HTTP HEAD | ≥ 90% return 2xx/3xx |
| Source tier ratio | Domain classification | ≥ 50% Tier 1 |
| Boundary handling | Error cases return explicit error, not fake report | 100% |
| Cost guard | Token count per case | < 50k tokens |

**Layer 2: Grounding Checks (LLM-as-judge, primary signal)**

| Check | Method | Pass Condition |
|-------|--------|----------------|
| Claim support rate | Per-claim support matrix: % of claims with ≥1 `supported` ClaimSupport | ≥ 80% |
| Citation resolution success | % of citations successfully resolved (reachable + content fetched) | ≥ 75% |
| Unsupported claim count | Claims with all supports `unsupported`/`unverifiable` | ≤ 2 per report |
| Abstention compliance | Ungrounded claims must be marked | 0 unmarked ungrounded |
| Factual consistency (secondary) | NLI-style: report summary vs abstract + title. Secondary signal only, not a gate. | Tracked but no hard threshold |

Judge prompts are version-controlled in `eval/prompts/`.

**Layer 3: Open-Ended Quality (human only, release gate)**

| Dimension | Scale |
|-----------|-------|
| Readability | 1–5 |
| Insight depth | 1–5 |
| Critical omission | yes/no + note |

### 4.3 Per-Run Artifacts

Saved to `eval/runs/YYYY-MM-DD-HHmmss/`:

| File | Content |
|------|---------|
| `meta.json` | Git commit, model, prompt version hash, runtime, total tokens |
| `results.jsonl` | Per-case three-layer scores + pass/fail |
| `reports/<case_id>.md` | Generated report |
| `traces/<case_id>.json` | LangGraph node sequence, tool calls, tokens per node |
| `diffs.md` | Auto-generated comparison with previous run |

### 4.4 Release Gate

All must pass:

```
Layer 1:
  structure_pass_rate       == 100%  (non-boundary cases)
  citation_reachable        >= 90%
  citation_tierAB_ratio     >= 40%   (Tier A + Tier B)
  boundary_case_handled     == 100%

Layer 2:
  claim_support_rate        >= 80%
  citation_resolution_rate  >= 75%
  unsupported_per_report    <= 2
  ungrounded_unmarked       == 0

Regression:
  layer2_pass_rate_delta    >= -2%   (vs previous release)

Layer 3:
  human_reviewed            >= 3 cases (fixed set: 1 strong paper, 1 failure-prone, 1 PDF)
  human_avg_readability     >= 3.0
  human_critical_miss       == 0
```

### 4.5 Trigger Strategy

| Scenario | What Runs | Expected Time |
|----------|-----------|---------------|
| Daily dev (post prompt/tool/graph change) | Layer 1 full + Layer 2 sample (5 cases) | < 10 min |
| Pre-release | Layer 1 + Layer 2 full + Layer 3 human (3 cases) | < 40 min |
| CI (added later) | Push/PR: L1 full + L2 sample; Release tag: full | per above |

CLI entry:
```bash
python -m eval.run --layer 1                # fast
python -m eval.run --layer 1,2 --sample 5   # daily with grounding
python -m eval.run --layer 1,2 --full       # pre-release
```

---

## 5. Task State Visualization

### 5.1 Backend: FastAPI SSE Endpoints

New endpoints added to the existing FastAPI app:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /tasks` | POST | Submit a report task, returns `task_id` |
| `GET /tasks/{task_id}/status` | SSE | Stream node events in real-time |
| `GET /tasks/{task_id}/result` | GET | Final report + verification stats |
| `GET /tasks` | GET | List recent tasks with status |

SSE event payload per node transition:
```json
{
  "event": "node_enter",
  "node": "verify_claims",
  "timestamp": "2026-03-29T10:05:32Z",
  "progress": 5,
  "total_nodes": 7,
  "tool_calls": [],
  "tokens_so_far": 12340
}
```

Additional events: `node_exit` (with duration, tool results), `error`, `complete`.

### 5.2 Task Execution Model

- Tasks run as `asyncio.Task` within the FastAPI process (MVP, same process)
- State stored in an in-memory dict `{task_id: TaskState}` (upgrade to Redis/SQLite later if needed)
- Graph nodes emit events via a callback that writes to an `asyncio.Queue` per task
- SSE endpoint reads from the queue and streams to the client

**MVP constraints (must hold for correct behavior):**
- Single process, single worker (`uvicorn --workers 1`)
- No hot reload in production (dev only)
- Task history lost on restart (acceptable for MVP; persistent storage deferred)
- Concurrent task limit: recommend ≤ 3 simultaneous tasks to avoid LLM rate limiting

### 5.3 Frontend: React + React Flow

Directory: `frontend/` (separate `package.json`, dev proxy to FastAPI)

| Component | Responsibility |
|-----------|---------------|
| `TaskSubmitForm` | Input arXiv URL or upload PDF, submit to `POST /tasks` |
| `GraphView` (React Flow) | Render the 11-node DAG; highlight current node; green = done, yellow = running, gray = pending, orange = limited, red = error |
| `ToolLogPanel` | Right sidebar: real-time tool call log (node name, tool, input, output, duration) |
| `ProgressBar` | Top bar: `N/11 nodes complete`, elapsed time, token count, degradation mode indicator |
| `ReportPreview` | On completion: rendered Markdown report + grounding statistics badge |
| `TaskHistory` | List of past tasks with status, click to view result |

Tech stack:
- React 18+ with TypeScript
- React Flow for node graph
- Tailwind CSS for styling
- EventSource (native) for SSE consumption
- Vite for build tooling

### 5.4 Development Workflow

```bash
# Terminal 1: backend
uvicorn src.api.app:app --reload --port 8000

# Terminal 2: frontend
cd frontend && npm run dev   # Vite dev server on :5173, proxy /api → :8000
```

Production: `npm run build` → static files served by FastAPI (`StaticFiles`) or Nginx.

---

## 6. Directory Structure (Post-Migration)

```
PaperReader_agent/
├── src/
│   ├── api/
│   │   ├── app.py              # FastAPI: mount routes
│   │   ├── routes/
│   │   │   ├── report.py       # POST /report (legacy sync)
│   │   │   ├── tasks.py        # POST /tasks, GET /tasks, GET /tasks/{id}/status (SSE), GET /tasks/{id}/result
│   │   └── schemas.py          # Pydantic request/response models
│   ├── graph/
│   │   ├── state.py            # AgentState TypedDict + NodeStatus
│   │   ├── builder.py          # build_report_graph() → CompiledGraph
│   │   ├── nodes/
│   │   │   ├── input_parse.py
│   │   │   ├── ingest_source.py
│   │   │   ├── extract_document_text.py
│   │   │   ├── normalize_metadata.py
│   │   │   ├── retrieve_evidence.py
│   │   │   ├── draft_report.py
│   │   │   ├── repair_report.py
│   │   │   ├── resolve_citations.py
│   │   │   ├── verify_claims.py
│   │   │   ├── apply_policy.py
│   │   │   └── format_output.py
│   │   └── callbacks.py        # Node event emitter for SSE + trace
│   ├── models/
│   │   ├── paper.py            # PaperMetadata, EvidenceBundle
│   │   ├── report.py           # DraftReport, Claim, Citation, FinalReport
│   │   └── task.py             # TaskState, TaskStatus enum
│   ├── verification/
│   │   ├── source_tiers.py     # Tier classification config + logic
│   │   ├── claim_judge.py      # LLM-based claim-evidence verification
│   │   ├── reachability.py     # Async URL HEAD checks
│   │   └── abstention.py       # Abstention marker rules
│   ├── tools/                  # (existing, unchanged)
│   ├── ingest/                 # (existing, unchanged)
│   ├── retrieval/              # (existing, unchanged)
│   ├── memory/                 # (existing, unchanged)
│   ├── corpus/                 # (existing, unchanged)
│   └── agent/
│       ├── cli.py              # (existing, updated to use new graph)
│       ├── llm.py              # (existing, unchanged)
│       ├── settings.py         # (existing, unchanged)
│       └── prompts.py          # (updated: structured claim output instructions)
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── TaskSubmitForm.tsx
│   │   │   ├── GraphView.tsx
│   │   │   ├── ToolLogPanel.tsx
│   │   │   ├── ProgressBar.tsx
│   │   │   ├── ReportPreview.tsx
│   │   │   └── TaskHistory.tsx
│   │   ├── hooks/
│   │   │   └── useTaskSSE.ts
│   │   └── types/
│   │       └── task.ts
│   └── tailwind.config.js
├── eval/
│   ├── cases.jsonl             # 20 eval cases
│   ├── prompts/
│   │   ├── claim_evidence_judge.txt
│   │   └── entailment_judge.txt
│   ├── runs/                   # Auto-generated per run
│   ├── __main__.py             # python -m eval.run entrypoint
│   ├── runner.py               # Orchestrates eval pipeline
│   ├── layers/
│   │   ├── hard_rules.py       # Layer 1 assertions
│   │   ├── grounding.py        # Layer 2 LLM judge
│   │   └── human.py            # Layer 3 human review I/O
│   └── diff.py                 # Cross-run comparison
├── docs/
│   ├── specs/
│   │   └── 2026-03-29-v2-architecture-design.md  # (this file)
│   └── ...
└── ...
```

---

## 7. Migration Path

Phase order (each phase is a branch → PR → merge):

| Phase | Scope | Depends On |
|-------|-------|------------|
| **Phase 1** | `src/graph/` + `src/models/`: StateGraph with 11 nodes (including ingestion normalization, citation resolution split, repair/policy), same LLM & tools, CLI works. Priorities within Phase 1: (1) source normalization, (2) citation resolution split, (3) structured node status, (4) degradation policy. | — |
| **Phase 2** | `src/verification/`: claim-evidence judge, source tiers, abstention | Phase 1 |
| **Phase 3** | `eval/`: 20 cases, Layer 1+2 runner, CLI trigger | Phase 1+2 |
| **Phase 4** | `src/api/routes/tasks.py` + SSE: async task execution with node events | Phase 1 |
| **Phase 5** | `frontend/`: React + React Flow + SSE consumer | Phase 4 |
| **Phase 6** | Integration: release gate, CI workflow, deployment config | Phase 3+5 |

---

## 8. Backward Compatibility & Deprecation

| Existing Feature | Disposition |
|------------------|------------|
| `create_react_agent` in `react_agent.py` | Replaced by `src/graph/builder.py`. Old module kept temporarily with deprecation warning during Phase 1; removed after CLI + API both confirmed working. |
| `generate_literature_report()` in `report.py` | Refactored to call the new graph internally, preserving the function signature so existing API routes work unchanged until Phase 4. |
| Chat/multi-turn REPL mode in `cli.py` | Deferred to post-v2. The CLI is updated to use the new graph for single-shot reports. `ConversationStore` / `LongTermMemory` remain in codebase but are not wired into the new graph. |
| `src/validators/citations_validator.py` | Absorbed into `format_output` node + Layer 1 eval. Module removed in Phase 1. |
| `src/retrieval/citations.py` (`Citation` dataclass) | Superseded by `src/models/report.py` Pydantic `Citation`. Module removed in Phase 1. |

## 9. Observability & Token Tracking

- Each graph node extracts `token_usage` from `LLMResult.llm_output` (when available) and adds to `AgentState.tokens_used` via the `operator.add` reducer.
- The `callbacks.py` emitter captures `(node_name, start_time, end_time, tool_calls, tokens_delta)` per node and writes them to both the SSE stream (for frontend) and the trace JSON (for eval).
- `diffs.md` auto-comparison: a table of per-case pass/fail deltas for L1 and L2 across the two runs, plus aggregate rate changes.
- Layer 3 human review UX: CLI script (`eval/layers/human.py`) prints each report, prompts for 1–5 ratings per dimension, stores results in `eval/runs/<run>/human_review.jsonl`.
- SSE reconnection (MVP limitation): no event replay on reconnect. Clients that disconnect will miss intermediate events but can poll `GET /tasks/{id}/result` for the final state. Replay via `last_event_id` deferred to post-MVP.

## 10. Out of Scope (Deferred)

- Multi-paper cross-paper synthesis/survey (post-v2; v2 supports sequential single-paper runs only)
- Multi-tenant / auth (post-v2)
- Idea generation workflow (post-v2)
- Self-built skills framework (post-v2)
- Chat/multi-turn conversational mode (post-v2)
- Docker / cloud deployment (Phase 6 or later)
- Prompt injection defense (post-v2, before public deployment)
- SSE event replay on reconnect (post-MVP)

# Literature Report Agent v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate from prebuilt ReAct agent to a custom 11-node StateGraph with citation verification, three-layer evaluation, and a React status dashboard.

**Architecture:** Custom LangGraph `StateGraph` with symmetric source ingestion, separated citation resolution and claim verification, typed degradation policy, and per-node structured status. FastAPI serves both the report API and SSE task events. React frontend visualizes the DAG in real-time.

**Tech Stack:** Python 3.10+, LangGraph, LangChain, FastAPI, Pydantic v2, pytest, React 18 + TypeScript, React Flow, Tailwind CSS, Vite

**Spec:** `docs/specs/2026-03-29-v2-architecture-design.md`

---

## Phase 1: Core Graph + Models

### Task 1: Pydantic Domain Models

**Files:**
- Create: `src/models/__init__.py`
- Create: `src/models/paper.py`
- Create: `src/models/report.py`
- Create: `src/models/task.py`
- Create: `tests/models/__init__.py`
- Create: `tests/models/test_paper.py`
- Create: `tests/models/test_report.py`
- Test: `tests/models/`

- [ ] **Step 1: Write failing tests for PaperMetadata and EvidenceBundle**

```python
# tests/models/test_paper.py
from src.models.paper import PaperMetadata, RagResult, WebResult, EvidenceBundle, NormalizedDocument

def test_paper_metadata_minimal():
    m = PaperMetadata(title="Attention", authors=["Vaswani"], abstract="We propose...")
    assert m.pdf_url is None
    assert m.published is None

def test_paper_metadata_full():
    m = PaperMetadata(
        title="Attention Is All You Need",
        authors=["Vaswani", "Shazeer"],
        abstract="The dominant...",
        pdf_url="https://arxiv.org/pdf/1706.03762",
        published="2017-06-12"
    )
    assert m.pdf_url.startswith("https://")

def test_evidence_bundle_empty():
    eb = EvidenceBundle(rag_results=[], web_results=[])
    assert len(eb.rag_results) == 0

def test_normalized_document():
    meta = PaperMetadata(title="T", authors=["A"], abstract="Ab")
    nd = NormalizedDocument(
        metadata=meta,
        document_text="full text",
        document_sections={"intro": "..."},
        source_manifest={"origin": "arxiv", "arxiv_id": "1706.03762"}
    )
    assert nd.metadata.title == "T"
    assert "intro" in nd.document_sections
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/artorias/devpro/PaperReader_agent && python -m pytest tests/models/test_paper.py -v`
Expected: FAIL (ImportError — modules don't exist yet)

- [ ] **Step 3: Implement paper models**

```python
# src/models/__init__.py
# (empty)

# src/models/paper.py
from __future__ import annotations
from pydantic import BaseModel

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

class NormalizedDocument(BaseModel):
    metadata: PaperMetadata
    document_text: str
    document_sections: dict[str, str]
    source_manifest: dict
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/models/test_paper.py -v`
Expected: 4 passed

- [ ] **Step 5: Write failing tests for report models**

```python
# tests/models/test_report.py
from src.models.report import (
    Citation, ClaimSupport, Claim, GroundingStats,
    DraftReport, ResolvedReport, VerifiedReport, FinalReport
)

def test_citation_defaults():
    c = Citation(label="[1]", url="https://arxiv.org/abs/1706.03762", reason="original paper")
    assert c.source_tier is None
    assert c.reachable is None

def test_claim_support():
    cs = ClaimSupport(
        claim_id="c1", citation_label="[1]",
        support_status="supported",
        evidence_excerpt="we propose the Transformer"
    )
    assert cs.support_status == "supported"

def test_claim_with_supports():
    c = Claim(id="c1", text="Transformer uses attention only", citation_labels=["[1]"])
    assert c.overall_status == "ungrounded"
    assert c.supports == []

def test_grounding_stats():
    gs = GroundingStats(
        total_claims=10, grounded=8, partial=1, ungrounded=0,
        abstained=1, tier_a_ratio=0.6, tier_b_ratio=0.2
    )
    assert gs.grounded + gs.partial + gs.ungrounded + gs.abstained == gs.total_claims

def test_draft_report_roundtrip():
    dr = DraftReport(
        sections={"title": "Attention"},
        claims=[Claim(id="c1", text="test", citation_labels=["[1]"])],
        citations=[Citation(label="[1]", url="https://example.com", reason="test")]
    )
    data = dr.model_dump()
    dr2 = DraftReport.model_validate(data)
    assert dr2.sections == dr.sections

def test_final_report_confidence():
    fr = FinalReport(
        sections={}, claims=[], citations=[],
        grounding_stats=GroundingStats(
            total_claims=0, grounded=0, partial=0,
            ungrounded=0, abstained=0, tier_a_ratio=0, tier_b_ratio=0
        ),
        report_confidence="high"
    )
    assert fr.report_confidence == "high"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `python -m pytest tests/models/test_report.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 7: Implement report models**

```python
# src/models/report.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel

class Citation(BaseModel):
    label: str
    url: str
    reason: str
    source_tier: Literal["A", "B", "C", "D"] | None = None
    reachable: bool | None = None
    fetched_content: str | None = None

class ClaimSupport(BaseModel):
    claim_id: str
    citation_label: str
    support_status: Literal["supported", "partial", "unsupported", "unverifiable"]
    evidence_excerpt: str | None = None
    reason: str | None = None
    judge_confidence: float | None = None

class Claim(BaseModel):
    id: str
    text: str
    citation_labels: list[str]
    supports: list[ClaimSupport] = []
    overall_status: Literal["grounded", "partial", "ungrounded", "abstained"] = "ungrounded"

class GroundingStats(BaseModel):
    total_claims: int
    grounded: int
    partial: int
    ungrounded: int
    abstained: int
    tier_a_ratio: float
    tier_b_ratio: float

class DraftReport(BaseModel):
    sections: dict[str, str]
    claims: list[Claim]
    citations: list[Citation]

class ResolvedReport(BaseModel):
    sections: dict[str, str]
    claims: list[Claim]
    citations: list[Citation]

class VerifiedReport(BaseModel):
    sections: dict[str, str]
    claims: list[Claim]
    citations: list[Citation]

class FinalReport(BaseModel):
    sections: dict[str, str]
    claims: list[Claim]
    citations: list[Citation]
    grounding_stats: GroundingStats
    report_confidence: Literal["high", "limited", "low"]
```

- [ ] **Step 8: Run all model tests**

Run: `python -m pytest tests/models/ -v`
Expected: all passed

- [ ] **Step 9: Commit**

```bash
git add src/models/ tests/models/
git commit -m "feat(models): add Pydantic domain models for paper, report, claim, citation"
```

---

### Task 2: AgentState + NodeStatus

**Files:**
- Create: `src/graph/__init__.py`
- Create: `src/graph/state.py`
- Create: `tests/graph/__init__.py`
- Create: `tests/graph/test_state.py`

- [ ] **Step 1: Write failing test for AgentState and NodeStatus**

```python
# tests/graph/test_state.py
from src.graph.state import AgentState, NodeStatus

def test_node_status_defaults():
    ns = NodeStatus(node="input_parse", status="pending")
    assert ns.tokens_delta == 0
    assert ns.warnings == []
    assert ns.repair_triggered is False

def test_agent_state_is_typed_dict():
    import typing
    hints = typing.get_type_hints(AgentState, include_extras=True)
    assert "raw_input" in hints
    assert "degradation_mode" in hints
    assert "node_statuses" in hints
    assert "tokens_used" in hints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/graph/test_state.py -v`
Expected: FAIL

- [ ] **Step 3: Implement state module**

```python
# src/graph/__init__.py
# (empty)

# src/graph/state.py
from __future__ import annotations
import operator
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel
from src.models.paper import NormalizedDocument, EvidenceBundle, PaperMetadata
from src.models.report import DraftReport, ResolvedReport, VerifiedReport, FinalReport

class NodeStatus(BaseModel):
    node: str
    status: Literal["pending", "running", "done", "limited", "failed", "skipped"]
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    warnings: list[str] = []
    error: str | None = None
    tokens_delta: int = 0
    repair_triggered: bool = False

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

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/graph/test_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/graph/ tests/graph/
git commit -m "feat(graph): add AgentState TypedDict and NodeStatus model"
```

---

### Task 3: Graph Nodes — Ingestion (input_parse, ingest_source, extract_document_text, normalize_metadata)

**Files:**
- Create: `src/graph/nodes/__init__.py`
- Create: `src/graph/nodes/input_parse.py`
- Create: `src/graph/nodes/ingest_source.py`
- Create: `src/graph/nodes/extract_document_text.py`
- Create: `src/graph/nodes/normalize_metadata.py`
- Create: `tests/graph/nodes/__init__.py`
- Create: `tests/graph/nodes/test_input_parse.py`
- Create: `tests/graph/nodes/test_ingest_source.py`

Each node is a function `(state: AgentState) -> dict` that returns a partial state update.

- [ ] **Step 1: Write failing test for input_parse**

```python
# tests/graph/nodes/test_input_parse.py
from src.graph.nodes.input_parse import input_parse

def test_parse_arxiv_url():
    state = {"raw_input": "https://arxiv.org/abs/1706.03762"}
    result = input_parse(state)
    assert result["source_type"] == "arxiv"
    assert result["arxiv_id"] == "1706.03762"

def test_parse_arxiv_id():
    state = {"raw_input": "1706.03762"}
    result = input_parse(state)
    assert result["source_type"] == "arxiv"
    assert result["arxiv_id"] == "1706.03762"

def test_parse_pdf_bytes():
    state = {"raw_input": "__pdf__", "pdf_text": "Some extracted text"}
    result = input_parse(state)
    assert result["source_type"] == "pdf"

def test_parse_invalid():
    state = {"raw_input": "not a valid input"}
    result = input_parse(state)
    assert len(result.get("errors", [])) > 0
```

- [ ] **Step 2: Run test — verify fail**

Run: `python -m pytest tests/graph/nodes/test_input_parse.py -v`

- [ ] **Step 3: Implement input_parse**

```python
# src/graph/nodes/__init__.py
# (empty)

# src/graph/nodes/input_parse.py
from __future__ import annotations
from src.tools.arxiv_paper import _extract_arxiv_id

def input_parse(state: dict) -> dict:
    raw = state.get("raw_input", "")
    pdf_text = state.get("pdf_text")

    if pdf_text:
        return {"source_type": "pdf"}

    arxiv_id = _extract_arxiv_id(raw)
    if arxiv_id:
        return {"source_type": "arxiv", "arxiv_id": arxiv_id}

    return {"errors": [f"input_parse: cannot determine source type from '{raw[:100]}'"]}
```

- [ ] **Step 4: Run test — verify pass**

- [ ] **Step 5: Write failing test for ingest_source (arXiv path — mock HTTP)**

```python
# tests/graph/nodes/test_ingest_source.py
from unittest.mock import patch, MagicMock
from src.graph.nodes.ingest_source import ingest_source

def test_ingest_arxiv():
    mock_entry = MagicMock()
    mock_entry.title = "Attention Is All You Need"
    mock_entry.summary = "The dominant..."
    mock_entry.published = "2017-06-12"
    mock_entry.authors = [MagicMock(name="Vaswani")]
    mock_entry.links = []

    with patch("src.graph.nodes.ingest_source.feedparser.parse") as mock_fp:
        mock_fp.return_value.entries = [mock_entry]
        result = ingest_source({"source_type": "arxiv", "arxiv_id": "1706.03762"})
    assert result["source_manifest"]["origin"] == "arxiv"
    assert "metadata" in result["source_manifest"] or result.get("errors")

def test_ingest_pdf():
    result = ingest_source({"source_type": "pdf", "pdf_text": "some text"})
    assert result["source_manifest"]["origin"] == "pdf"
```

- [ ] **Step 6: Implement ingest_source**

```python
# src/graph/nodes/ingest_source.py
from __future__ import annotations
import feedparser
import urllib.parse
from src.tools.arxiv_paper import _extract_arxiv_id

def ingest_source(state: dict) -> dict:
    source_type = state.get("source_type")

    if source_type == "pdf":
        return {"source_manifest": {"origin": "pdf"}}

    arxiv_id = state.get("arxiv_id")
    if not arxiv_id:
        return {"errors": ["ingest_source: missing arxiv_id"]}

    base_url = "http://export.arxiv.org/api/query"
    params = {"search_query": f"id:{arxiv_id}", "start": 0, "max_results": 1}
    api_url = f"{base_url}?{urllib.parse.urlencode(params)}"

    try:
        feed = feedparser.parse(api_url)
        if not feed.entries:
            return {"errors": [f"ingest_source: no arXiv entry for {arxiv_id}"]}
        entry = feed.entries[0]
        title = entry.title.replace("\n", " ").strip()
        abstract = entry.summary.replace("\n", " ").strip()
        authors = [a.name for a in entry.authors]
        published = getattr(entry, "published", None)
        pdf_url = None
        for link in getattr(entry, "links", []):
            if getattr(link, "type", "") == "application/pdf" or getattr(link, "title", "") == "pdf":
                pdf_url = link.href
                break
        return {
            "source_manifest": {
                "origin": "arxiv",
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "published": published,
                "pdf_url": pdf_url,
            }
        }
    except Exception as e:
        return {"errors": [f"ingest_source: {e}"]}
```

- [ ] **Step 7: Run tests — verify pass**

Run: `python -m pytest tests/graph/nodes/ -v`

- [ ] **Step 8: Implement extract_document_text and normalize_metadata** (similar pattern: test → implement → verify)

`extract_document_text`: downloads PDF from `source_manifest["pdf_url"]` (arXiv) or uses existing `pdf_text` (PDF upload), stores result in `pdf_text`.

`normalize_metadata`: builds `NormalizedDocument` from `source_manifest` + `pdf_text`. For arXiv, metadata comes from manifest. For PDF, uses LLM to extract title/authors from first 2000 chars (mock in tests).

- [ ] **Step 9: Run all node tests**

Run: `python -m pytest tests/graph/nodes/ -v`

- [ ] **Step 10: Commit**

```bash
git add src/graph/nodes/ tests/graph/nodes/
git commit -m "feat(graph): implement ingestion nodes (input_parse, ingest, extract, normalize)"
```

---

### Task 4: Graph Nodes — Core Pipeline (retrieve_evidence, draft_report, repair_report)

**Files:**
- Create: `src/graph/nodes/retrieve_evidence.py`
- Create: `src/graph/nodes/draft_report.py`
- Create: `src/graph/nodes/repair_report.py`
- Create: `tests/graph/nodes/test_draft_report.py`

- [ ] **Step 1: Write failing test for retrieve_evidence**

Test uses mocks for `rag_search` and `fetch_webpage_text` to avoid network calls.

- [ ] **Step 2: Implement retrieve_evidence**

Reads `normalized_doc.metadata.abstract` and `normalized_doc.document_text` as queries for RAG + web fetch (parallel via asyncio). Populates `evidence: EvidenceBundle`.

- [ ] **Step 3: Write failing test for draft_report**

Mock LLM to return a JSON-structured response. Verify `DraftReport` is correctly parsed from LLM output.

- [ ] **Step 4: Implement draft_report**

Calls LLM with structured output prompt. Parses response into `DraftReport`. If parse fails, falls back to text extraction.

- [ ] **Step 5: Write failing test for repair_report**

Test two cases: (a) report has all sections → pass-through, (b) report missing citations → triggers repair.

- [ ] **Step 6: Implement repair_report**

Checks for required sections. If missing, calls LLM once to repair. Sets `NodeStatus.repair_triggered = True` when repair happens.

- [ ] **Step 7: Run all tests**

Run: `python -m pytest tests/graph/nodes/ -v`

- [ ] **Step 8: Commit**

```bash
git add src/graph/nodes/retrieve_evidence.py src/graph/nodes/draft_report.py src/graph/nodes/repair_report.py tests/graph/nodes/
git commit -m "feat(graph): implement core pipeline nodes (retrieve, draft, repair)"
```

---

### Task 5: Graph Builder + Degradation Policy

**Files:**
- Create: `src/graph/builder.py`
- Create: `src/graph/callbacks.py`
- Create: `tests/graph/test_builder.py`

- [ ] **Step 1: Write failing test for graph compilation**

```python
# tests/graph/test_builder.py
from src.graph.builder import build_report_graph

def test_graph_compiles():
    graph = build_report_graph()
    assert graph is not None

def test_graph_has_expected_nodes():
    graph = build_report_graph()
    node_names = set(graph.nodes.keys())
    expected = {
        "input_parse", "ingest_source", "extract_document_text",
        "normalize_metadata", "retrieve_evidence", "draft_report",
        "repair_report", "resolve_citations", "verify_claims",
        "apply_policy", "format_output"
    }
    assert expected.issubset(node_names)
```

- [ ] **Step 2: Implement graph builder**

```python
# src/graph/builder.py
from langgraph.graph import StateGraph, END
from src.graph.state import AgentState
from src.graph.nodes.input_parse import input_parse
from src.graph.nodes.ingest_source import ingest_source
from src.graph.nodes.extract_document_text import extract_document_text
from src.graph.nodes.normalize_metadata import normalize_metadata
from src.graph.nodes.retrieve_evidence import retrieve_evidence
from src.graph.nodes.draft_report import draft_report
from src.graph.nodes.repair_report import repair_report
from src.graph.nodes.resolve_citations import resolve_citations
from src.graph.nodes.verify_claims import verify_claims
from src.graph.nodes.apply_policy import apply_policy
from src.graph.nodes.format_output import format_output

def _should_abort(state: dict) -> str:
    if state.get("degradation_mode") == "safe_abort":
        return "format_output"
    return "continue"

def build_report_graph():
    g = StateGraph(AgentState)

    g.add_node("input_parse", input_parse)
    g.add_node("ingest_source", ingest_source)
    g.add_node("extract_document_text", extract_document_text)
    g.add_node("normalize_metadata", normalize_metadata)
    g.add_node("retrieve_evidence", retrieve_evidence)
    g.add_node("draft_report", draft_report)
    g.add_node("repair_report", repair_report)
    g.add_node("resolve_citations", resolve_citations)
    g.add_node("verify_claims", verify_claims)
    g.add_node("apply_policy", apply_policy)
    g.add_node("format_output", format_output)

    g.set_entry_point("input_parse")
    g.add_edge("input_parse", "ingest_source")
    g.add_edge("ingest_source", "extract_document_text")
    g.add_edge("extract_document_text", "normalize_metadata")

    g.add_conditional_edges("normalize_metadata", _should_abort,
        {"continue": "retrieve_evidence", "format_output": "format_output"})
    g.add_edge("retrieve_evidence", "draft_report")
    g.add_edge("draft_report", "repair_report")
    g.add_edge("repair_report", "resolve_citations")
    g.add_edge("resolve_citations", "verify_claims")
    g.add_edge("verify_claims", "apply_policy")
    g.add_edge("apply_policy", "format_output")
    g.add_edge("format_output", END)

    return g.compile()
```

- [ ] **Step 3: Run test — verify pass**

- [ ] **Step 4: Implement callbacks.py** (node event emitter — captures start/end/tokens per node, writes to `asyncio.Queue`)

- [ ] **Step 5: Commit**

```bash
git add src/graph/builder.py src/graph/callbacks.py tests/graph/test_builder.py
git commit -m "feat(graph): graph builder with 11 nodes, degradation routing, callbacks"
```

---

### Task 6: Wire CLI to New Graph

**Files:**
- Modify: `src/agent/cli.py`
- Modify: `src/agent/report.py`
- Create: `tests/test_integration_cli.py`

- [ ] **Step 1: Write integration test — graph produces markdown output for a mock arXiv input**

- [ ] **Step 2: Refactor `generate_literature_report()` in `report.py` to call the new graph internally**, preserving the existing function signature (so `app.py` API still works)

- [ ] **Step 3: Update CLI `_run_report()` to use new graph**

- [ ] **Step 4: Run integration test**

- [ ] **Step 5: Manual smoke test**

Run: `python -m src.agent.cli` → enter `1706.03762` → confirm report generates

- [ ] **Step 6: Commit**

```bash
git add src/agent/cli.py src/agent/report.py tests/test_integration_cli.py
git commit -m "feat(agent): wire CLI and report to new StateGraph"
```

---

## Phase 2: Verification Subsystem

### Task 7: Source Tier Classification

**Files:**
- Create: `src/verification/__init__.py`
- Create: `src/verification/source_tiers.py`
- Create: `tests/verification/__init__.py`
- Create: `tests/verification/test_source_tiers.py`

- [ ] **Step 1: Write failing tests** — classify known URLs into A/B/C/D tiers

- [ ] **Step 2: Implement** — domain regex map, `classify_url(url: str) -> Literal["A","B","C","D"]`

- [ ] **Step 3: Run tests — verify pass**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(verification): source tier classification (A/B/C/D)"
```

---

### Task 8: URL Reachability

**Files:**
- Create: `src/verification/reachability.py`
- Create: `tests/verification/test_reachability.py`

- [ ] **Step 1: Write failing tests** — mock httpx: HEAD succeeds, HEAD fails + GET fallback, both fail

- [ ] **Step 2: Implement** — async `check_url_reachable(url) -> bool`, HEAD first, GET fallback, 5s timeout

- [ ] **Step 3: Commit**

---

### Task 9: resolve_citations Node

**Files:**
- Create: `src/graph/nodes/resolve_citations.py`
- Create: `tests/graph/nodes/test_resolve_citations.py`

- [ ] **Step 1: Write failing tests** — citations get tier + reachability + fetched_content

- [ ] **Step 2: Implement** — calls source_tiers + reachability + content fetch per citation

- [ ] **Step 3: Commit**

---

### Task 10: Claim-Evidence Judge

**Files:**
- Create: `src/verification/claim_judge.py`
- Create: `tests/verification/test_claim_judge.py`

- [ ] **Step 1: Write failing tests** — mock LLM judge, verify ClaimSupport output

- [ ] **Step 2: Implement** — LLM prompt per (claim, citation) → ClaimSupport

- [ ] **Step 3: Commit**

---

### Task 11: verify_claims + apply_policy Nodes

**Files:**
- Create: `src/graph/nodes/verify_claims.py`
- Create: `src/graph/nodes/apply_policy.py`
- Create: `tests/graph/nodes/test_verify_claims.py`
- Create: `tests/graph/nodes/test_apply_policy.py`

- [ ] **Step 1: Test verify_claims** — given ResolvedReport with fetched citations, produces VerifiedReport with ClaimSupport entries

- [ ] **Step 2: Implement verify_claims**

- [ ] **Step 3: Test apply_policy** — test report-level confidence thresholds (≥80% → high, 50-79% → limited, <50% → low)

- [ ] **Step 4: Implement apply_policy** — claim-level abstention markers + report-level confidence

- [ ] **Step 5: Commit**

---

### Task 12: format_output Node

**Files:**
- Create: `src/graph/nodes/format_output.py`
- Create: `tests/graph/nodes/test_format_output.py`

- [ ] **Step 1: Test** — FinalReport with grounding stats renders to Markdown with stats block

- [ ] **Step 2: Implement** — pure formatting, no semantic changes

- [ ] **Step 3: Commit**

---

## Phase 3: Evaluation Pipeline

### Task 13: Eval Cases + Layer 1 Runner

**Files:**
- Modify: `eval/cases.jsonl` (expand to 20 cases)
- Create: `eval/__init__.py`
- Create: `eval/__main__.py`
- Create: `eval/runner.py`
- Create: `eval/layers/__init__.py`
- Create: `eval/layers/hard_rules.py`
- Create: `eval/prompts/claim_evidence_judge.txt`
- Create: `eval/prompts/entailment_judge.txt`
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/test_hard_rules.py`

- [ ] **Step 1: Write 20 eval cases in `eval/cases.jsonl`** (8 arXiv, 4 PDF, 3 sequential, 3 gold, 2 boundary)

- [ ] **Step 2: Write failing tests for Layer 1 checks** — structure completeness, citation format, cost guard

- [ ] **Step 3: Implement Layer 1** — `hard_rules.py` with `run_layer1(report_md: str, case: dict) -> dict`

- [ ] **Step 4: Implement runner.py** — `python -m eval.run --layer 1` entry point, writes to `eval/runs/`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(eval): Layer 1 hard-rule checks + 20 eval cases + CLI runner"
```

---

### Task 14: Layer 2 Grounding Checks

**Files:**
- Create: `eval/layers/grounding.py`
- Create: `tests/eval/test_grounding.py`

- [ ] **Step 1: Write judge prompts** in `eval/prompts/`

- [ ] **Step 2: Write failing tests** — mock LLM judge, verify claim support rate computation

- [ ] **Step 3: Implement** — `run_layer2(report, trace, case) -> dict`

- [ ] **Step 4: Commit**

---

### Task 15: Diff + Release Gate

**Files:**
- Create: `eval/diff.py`
- Modify: `eval/runner.py` (add `--full` mode and gate checking)

- [ ] **Step 1: Implement diff.py** — compare two `results.jsonl`, output `diffs.md`

- [ ] **Step 2: Add release gate check** — load thresholds, compare against results

- [ ] **Step 3: Commit**

---

## Phase 4: FastAPI Task SSE

### Task 16: Task Routes + SSE

**Files:**
- Create: `src/api/routes/__init__.py`
- Create: `src/api/routes/tasks.py`
- Modify: `src/api/app.py` (mount new router)
- Create: `src/models/task.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/test_tasks.py`

- [ ] **Step 1: Write failing test** — POST /tasks returns task_id, GET /tasks lists tasks

- [ ] **Step 2: Implement task routes** — `POST /tasks`, `GET /tasks`, `GET /tasks/{id}/status` (SSE), `GET /tasks/{id}/result`

- [ ] **Step 3: Write SSE test** — mock graph execution, verify SSE events stream node_enter/node_exit

- [ ] **Step 4: Mount router in app.py**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(api): async task routes with SSE status streaming"
```

---

## Phase 5: React Frontend

### Task 17: Frontend Scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/types/task.ts`

- [ ] **Step 1: Initialize** — `npm create vite@latest frontend -- --template react-ts`

- [ ] **Step 2: Install deps** — `npm install reactflow tailwindcss @tailwindcss/vite`

- [ ] **Step 3: Configure Vite proxy** — `/api` → `http://localhost:8000`

- [ ] **Step 4: Commit**

---

### Task 18: React Components

**Files:**
- Create: `frontend/src/components/TaskSubmitForm.tsx`
- Create: `frontend/src/components/GraphView.tsx`
- Create: `frontend/src/components/ToolLogPanel.tsx`
- Create: `frontend/src/components/ProgressBar.tsx`
- Create: `frontend/src/components/ReportPreview.tsx`
- Create: `frontend/src/components/TaskHistory.tsx`
- Create: `frontend/src/hooks/useTaskSSE.ts`

- [ ] **Step 1: Implement useTaskSSE hook** — EventSource consumer, parses SSE events into state

- [ ] **Step 2: Implement TaskSubmitForm** — arXiv URL input + PDF upload

- [ ] **Step 3: Implement GraphView** — React Flow 11-node DAG with status coloring

- [ ] **Step 4: Implement ToolLogPanel** — scrollable log panel

- [ ] **Step 5: Implement ProgressBar + ReportPreview + TaskHistory**

- [ ] **Step 6: Wire App.tsx** — layout: submit form top, graph center, log right, preview below

- [ ] **Step 7: Smoke test** — `npm run dev` + backend running, submit an arXiv URL, see graph animate

- [ ] **Step 8: Commit**

```bash
git commit -m "feat(frontend): React dashboard with graph visualization and SSE"
```

---

## Phase 6: Integration

### Task 19: End-to-End Test + CI Prep

- [ ] **Step 1: Write E2E test** — start FastAPI, POST /tasks, consume SSE until complete, verify report

- [ ] **Step 2: Run full eval** — `python -m eval.run --layer 1,2 --full`

- [ ] **Step 3: Create `.github/workflows/ci.yml`** — pytest + Layer 1 eval on push

- [ ] **Step 4: Commit and push**

```bash
git commit -m "ci: add GitHub Actions workflow with pytest and Layer 1 eval"
```

---

## Cleanup Checklist (after all phases)

- [ ] Remove `src/agent/react_agent.py` (replaced by `src/graph/builder.py`)
- [ ] Remove `src/validators/citations_validator.py` (absorbed into repair_report + eval)
- [ ] Remove `src/retrieval/citations.py` (superseded by `src/models/report.py`)
- [ ] Update `README.md` with new architecture diagram and usage
- [ ] Tag release: `git tag -a v2.0.0 -m "v2: custom StateGraph, citation verification, eval, React dashboard"`

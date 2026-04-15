# Current Architecture And Usage

## 1. Overall Stack

### Backend

- Python 3.10+
- FastAPI + Uvicorn
- Pydantic v2
- SQLAlchemy 2
- LangGraph + LangChain Core
- DeepSeek via OpenAI-compatible API

### Data And Retrieval

- PostgreSQL is the only durable database
- `pgvector` is optional for PostgreSQL vector support
- FAISS is used for local vector retrieval/indexing
- SearXNG is used for external search aggregation

### Frontend

- React 19
- TypeScript 5
- Vite 8
- Tailwind CSS 4
- `@xyflow/react` for graph visualization
- `react-markdown` + `remark-gfm` + `remark-math` + `rehype-katex` + `katex`

## 2. Runtime Architecture

### Task Runtime

- The API accepts tasks through `/tasks`
- Task execution is dispatched through a background `ThreadPoolExecutor`
- Live task state is kept in memory for status polling / SSE
- Long-lived task snapshots and final results are persisted to PostgreSQL

### Persistence

- Task snapshot persistence lives in `src/db/task_persistence.py`
- Durable report/task reads are exposed through:
  - `GET /tasks/{task_id}`
  - `GET /tasks/{task_id}/result`
- Durable persistence is PostgreSQL-only

## 3. Graph Architecture

### Report Graph

The report graph is still a staged LangGraph pipeline:

`input_parse -> ingest_source -> extract_document_text -> normalize_metadata -> retrieve_evidence -> classify_paper_type -> draft_report/report_frame/survey_intro_outline -> repair_report -> resolve_citations -> verify_claims -> apply_policy -> format_output`

Notes:

- `draft_report` is used for draft mode
- `report_frame` is used for regular full reports
- `survey_intro_outline` is used for survey papers
- `format_output` is the final user-facing report assembly node

### Research Graph

The current research graph is:

`clarify -> search_plan -> search -> extract -> draft -> review -> persist_artifacts`

Important nuance:

- The graph still advances stage by stage for correctness
- Parallelism is currently implemented inside heavy nodes, not as a fully parallel DAG

#### Current Parallelized Parts

`search`

- Executes all SearXNG queries in parallel with `ThreadPoolExecutor`
- Fetches arXiv metadata in parallel
- Current implementation caps worker count with `max_workers = min(8, len(all_queries))`

`extract`

- Performs batched LLM-based paper-card extraction
- Current batching is `3` papers per batch
- This is node-internal throughput optimization rather than DAG-level parallel fan-out

#### Draft / Review / Persist

`draft`

- Synthesizes `paper_cards` into `DraftReport + draft_markdown`
- Falls back to a template-based draft when the LLM path fails

`review`

- Runs grounding internally via `resolve_citations -> verify_claims -> format_output`
- Produces `resolved_report`, `verified_report`, `final_report`, and `ReviewFeedback`

`persist_artifacts`

- Persists workspace-facing artifacts after review passes

## 4. Frontend Rendering Architecture

The research-mode preview now has structured rendering rather than raw JSON-only fallback.

### Research Preview Sections

`BriefCard`

- topic
- goal
- sub-questions
- confidence badge
- ambiguities / follow-up state

`SearchPlanCard`

- query groups
- query/group/hit statistics
- planner warnings

`PaperCardsSection`

- paper title
- authors
- methods
- datasets
- summary

`DraftPreview`

- Markdown rendering via shared `MarkdownRenderer`

`ReviewFeedbackCard`

- severity-based issue display
- coverage gaps

### Frontend Types

Research-mode task types include:

- `brief`
- `search_plan`
- `rag_result`
- `paper_cards`
- `draft_report`
- `review_feedback`
- `review_passed`

The richer grounded report payload is currently easiest to consume from:

- `GET /tasks/{task_id}/result`

That persisted JSON now includes `resolved_report`, `verified_report`, and `final_report` for research tasks when grounding succeeds.

## 5. Main API Entry Points

### Legacy Single-Shot Report Endpoints

- `POST /report`
- `POST /report/upload_pdf`

These are still useful for one-shot report generation without task orchestration.

### Task-Oriented Endpoints

- `POST /tasks`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `GET /tasks/{task_id}/result`
- `GET /tasks/{task_id}/events`
- `POST /tasks/{task_id}/chat`
- `GET /tasks/{task_id}/trace`
- `GET /tasks/{task_id}/review`

## 6. Basic Usage

### 6.1 Environment

Create `.env` from `.env.example` and configure at least:

```ini
DEEPSEEK_API_KEY=...
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-reasoner
DATABASE_URL=postgresql://researchuser:123@127.0.0.1:5432/researchagent
SEARXNG_BASE_URL=http://127.0.0.1:8080
```

### 6.2 Start Backend

```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

### 6.3 Start Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` and `/tasks` to the FastAPI backend.

### 6.4 One-Shot Report

```bash
curl -X POST "http://127.0.0.1:8000/report" \
  -H "Content-Type: application/json" \
  -d '{"arxiv_url_or_id":"1706.03762"}'
```

### 6.5 Research Workflow Task

```bash
curl -X POST "http://127.0.0.1:8000/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "research",
    "input_value": "调研医疗垂类大模型中的 AI agent 发展",
    "source_type": "research",
    "report_mode": "draft"
  }'
```

Then poll:

```bash
curl "http://127.0.0.1:8000/tasks/<task_id>"
curl "http://127.0.0.1:8000/tasks/<task_id>/result"
curl "http://127.0.0.1:8000/tasks/<task_id>/trace"
```

## 7. Maintenance Guidance

- Keep stack and hard constraints in `AGENTS.md`, `.cursorrules`, and `.cursor/rules/*.mdc`
- Keep workflow topology, node lists, and usage examples in `docs/`
- When graph topology changes, update this file instead of encoding the topology into rule files

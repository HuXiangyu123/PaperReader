# AGENTS

## Project Stack

- Backend: Python 3.10+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2
- Agent orchestration: LangGraph + LangChain Core + OpenAI-compatible chat clients
- Primary LLM provider: DeepSeek via OpenAI-compatible API
- Primary database: PostgreSQL only
- Optional vector extension: pgvector on PostgreSQL
- Local/vector retrieval: FAISS
- Search aggregation: SearXNG
- Frontend: React 19, TypeScript 5, Vite 8, Tailwind CSS 4, `@xyflow/react`
- Markdown/math rendering: `react-markdown`, `remark-gfm`, `remark-math`, `rehype-katex`, `katex`
- Testing: pytest, FastAPI `TestClient`

## Hard Rules

- Do not introduce SQLite for metadata, task state, report persistence, or test fixtures.
- All long-lived persistence must go through PostgreSQL using `DATABASE_URL`.
- Runtime in-memory stores are allowed only for transient execution state or local UI buffering; they are not a substitute for durable storage.
- If a feature needs persistence, implement it in `src/db/*` or a PostgreSQL-backed service layer instead of adding local `.sqlite` files.
- When writing scripts or tests that need environment config, load `.env` explicitly with `load_dotenv(".env")` to avoid implicit path issues.
- When updating task/report persistence, keep `/tasks`, `/tasks/{id}`, and `/tasks/{id}/result` behavior aligned.
- Do not encode volatile workflow topology or stage-by-stage architecture notes in this file; keep that in `docs/`.

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.models.paper import EvidenceBundle, RagResult, WebResult


QUERY_PLANNER_SYSTEM_PROMPT = """You are a research retrieval planner.
Given a paper title and abstract, propose concise search queries for retrieving related evidence.
Requirements:
- Output 3-4 queries, each <= 18 words.
- Cover different angles: core method, task/benchmark, and related-work keywords.
- Prefer concrete technical terms from the paper title/abstract.
Return JSON only in this format:
{"queries": ["...", "...", "..."]}
"""


def _extract_json_block(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
    if clean.startswith("{") and clean.endswith("}"):
        return clean
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        return clean[start : end + 1]
    return clean


def _build_candidate_queries(doc) -> tuple[list[str], str | None]:
    """Generate candidate search queries; fall back to abstract/text query on any failure."""
    base_query = (doc.metadata.abstract or doc.document_text[:2000]).strip()
    if not base_query:
        return [], "retrieve_evidence: empty base query"

    title = doc.metadata.title or "Untitled"
    abstract = doc.metadata.abstract or ""

    fallback_queries = [base_query]
    if title and title not in {"Unknown", "Untitled"}:
        fallback_queries.append(title)

    try:
        from src.agent.settings import Settings
        from src.agent.llm import build_chat_llm

        settings = Settings.from_env()
        llm = build_chat_llm(settings)
        user_prompt = (
            f"Title: {title}\n\n"
            f"Abstract: {abstract}\n\n"
            "Generate 3-4 retrieval queries as JSON."
        )
        resp = llm.invoke([
            SystemMessage(content=QUERY_PLANNER_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        text = resp.content if hasattr(resp, "content") else str(resp)
        clean = _extract_json_block(text)

        data = json.loads(clean)
        queries = []
        for q in data.get("queries", []):
            if not isinstance(q, str):
                continue
            sq = " ".join(q.strip().split())
            if not sq:
                continue
            # Keep query concise for better lexical/vector retrieval stability.
            if len(sq) > 180:
                sq = sq[:180].strip()
            queries.append(sq)
        if not queries:
            return fallback_queries, "retrieve_evidence: planner returned empty queries, used fallback"
        # Include base query to stabilize recall.
        merged = [queries[0], base_query, *queries[1:]]
        deduped: list[str] = []
        for q in merged:
            if q not in deduped:
                deduped.append(q)
        return deduped[:4], None
    except Exception as e:
        return fallback_queries, f"retrieve_evidence: query planner failed ({e}), used fallback"


def retrieve_evidence(state: dict) -> dict:
    doc = state.get("normalized_doc")
    if not doc:
        return {"errors": ["retrieve_evidence: no normalized_doc"]}

    queries, planner_warning = _build_candidate_queries(doc)
    rag_results: list[RagResult] = []
    web_results: list[WebResult] = []
    warnings: list[str] = []
    if planner_warning:
        warnings.append(planner_warning)

    try:
        from src.tools.rag_search import rag_search

        seen_chunks: set[str] = set()
        rank = 0
        for query in queries:
            raw = rag_search.invoke(query)
            if raw.startswith("Error") or raw.startswith("No relevant"):
                continue
            for chunk in raw.split("\n---\n"):
                text = chunk.strip()
                if not text or text in seen_chunks:
                    continue
                seen_chunks.add(text)
                rag_results.append(
                    RagResult(text=text, doc_id=f"rag-{rank}", score=max(0.1, 1.0 - rank * 0.08))
                )
                rank += 1
                if rank >= 12:
                    break
            if rank >= 12:
                break
    except Exception as e:
        warnings.append(f"retrieve_evidence: RAG search failed: {e}")

    try:
        from src.tools.web_fetch import fetch_webpage_text

        title = doc.metadata.title
        if title and title != "Unknown" and title != "Untitled":
            search_url = f"https://scholar.google.com/scholar?q={title.replace(' ', '+')}"
            result = fetch_webpage_text.invoke({"url": search_url, "max_chars": 4000})
            if isinstance(result, dict):
                web_results.append(
                    WebResult(url=result["url"], text=result["text"], status_code=200)
                )
    except Exception as e:
        warnings.append(f"retrieve_evidence: web search failed: {e}")

    evidence = EvidenceBundle(rag_results=rag_results, web_results=web_results)
    result: dict = {"evidence": evidence}
    if warnings:
        result["warnings"] = warnings
    return result

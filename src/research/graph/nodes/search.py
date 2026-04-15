"""Search node — Phase 2: 执行 SearchPlan 查询，产出 RagResult。

策略（3 路并行）：
1. SearXNG（广度召回）：关键词匹配，快速广覆盖
2. arXiv API（精度）：直接 API 查询，metadata 完整
3. DeepXiv（补充 + 热度）：TLDR 摘要、社交热度发现

三者并行执行，统一去重后输出 paper_candidates。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from src.models.paper import RagResult
from src.tasking.trace_wrapper import get_trace_store, trace_node

logger = logging.getLogger(__name__)


def _run_searxng_queries(
    all_queries: list[tuple[str, str, int]],
) -> tuple[list[dict], list[dict]]:
    """
    并行执行所有 SearXNG 查询，返回 (search_results, query_traces)。
    """
    from src.tools.search_tools import _searxng_search

    MAX_WORKERS = min(8, len(all_queries))
    search_results: list[dict] = []
    query_traces: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_searxng_search, q, engines="arxiv", max_results=h): q
            for q, _, h in all_queries
        }
        for future in as_completed(futures):
            q = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                query_traces.append({"query": q, "status": "error", "error": str(exc)})
                continue

            if not result.get("ok"):
                query_traces.append({"query": q, "status": "error", "error": result.get("error")})
                continue

            hits = result.get("hits", [])
            query_traces.append({
                "query": q,
                "status": "success",
                "hits_count": len(hits),
            })
            for hit in hits:
                hit["_search_query"] = q
            search_results.extend(hits)

    return search_results, query_traces


def _run_arxiv_direct_search(
    all_queries: list[tuple[str, str, int]],
    year_filter: str | None = None,
) -> list[dict]:
    """
    直接通过 arXiv API 执行每个查询，返回 paper metadata 列表。

    每个查询最多取 10 条结果。并行执行所有查询。
    """
    from src.tools.arxiv_api import search_arxiv_direct

    results: list[dict] = []

    def _search_one(q: str) -> list[dict]:
        try:
            papers = search_arxiv_direct(q, max_results=10, year_filter=year_filter)
            for paper in papers:
                paper["_source"] = "arxiv_direct"
                paper["_search_query"] = q
            return papers
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=min(8, len(all_queries))) as pool:
        futures = {pool.submit(_search_one, q): q for q, _, _ in all_queries}
        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception:
                pass

    return results


# ─── node ─────────────────────────────────────────────────────────────────────


@trace_node(node_name="search", stage="search", store=get_trace_store())
def search_node(state: dict) -> dict:
    """
    Phase 2 搜索节点。

    输入：state.search_plan, state.brief
    输出：state.rag_result（含 paper_candidates）

    并行策略：
    - SearXNG 查询（广度）：并行执行所有查询
    - arXiv API 查询（精度）：并行执行，直接获取 metadata
    - 两者并行，合并去重，确保不漏不重
    """
    from src.tools.arxiv_api import enrich_search_results_with_arxiv

    search_plan = state.get("search_plan")
    brief = state.get("brief")

    if not search_plan:
        logger.warning("[search_node] no search_plan, skipping")
        return {"rag_result": None}

    query_groups = search_plan.get("query_groups", [])
    plan_goal = search_plan.get("plan_goal", "")
    time_range = search_plan.get("time_range") if search_plan else None

    # ── Step 1：收集所有查询 ──────────────────────────────────────────
    all_queries: list[tuple[str, str, int]] = []
    for group in query_groups:
        gid = group.get("group_id", "unknown")
        hits = group.get("expected_hits", 10)
        for q in group.get("queries", []):
            if q:
                all_queries.append((q, gid, hits))

    if not all_queries:
        logger.warning("[search_node] no queries in search_plan")
        return {"rag_result": None}

    # ── Step 2：SearXNG + arXiv API 并行执行 ──────────────────────────
    # 当 time_range 为空时，强制默认 2020 年过滤（避免搜到 2016 年旧论文）
    parsed_year_filter = _time_filter_from_range(time_range)
    effective_year_filter = parsed_year_filter
    if not effective_year_filter:
        from src.tools.arxiv_api import DEFAULT_YEAR_FILTER
        effective_year_filter = DEFAULT_YEAR_FILTER
        logger.info("[search_node] no time_range, applying default year filter: %s", effective_year_filter)

    with ThreadPoolExecutor(max_workers=3) as pool:
        searxng_future = pool.submit(_run_searxng_queries, all_queries)
        arxiv_future = pool.submit(_run_arxiv_direct_search, all_queries, effective_year_filter)
        deepxiv_future = pool.submit(_run_deepxiv_queries, all_queries, effective_year_filter)

    searxng_results, query_traces = searxng_future.result()
    arxiv_direct_results = arxiv_future.result()
    deepxiv_results = deepxiv_future.result()

    logger.info(
        "[search_node] searxng hits=%d, arxiv_direct hits=%d, deepxiv hits=%d",
        len(searxng_results), len(arxiv_direct_results), len(deepxiv_results),
    )

    # ── Step 3：合并候选并去重 ────────────────────────────────────────
    # 优先级：arXiv API > DeepXiv > SearXNG（metadata 完整性依次递减）
    combined: list[dict] = []
    seen_urls: set[str] = set()
    seen_arxiv_ids: set[str] = set()

    for paper in arxiv_direct_results:
        aid = paper.get("arxiv_id") or ""
        url = paper.get("url", "")
        if aid and aid in seen_arxiv_ids:
            continue
        if url and url in seen_urls:
            continue
        if aid:
            seen_arxiv_ids.add(aid)
        if url:
            seen_urls.add(url)
        combined.append(paper)

    for paper in deepxiv_results:
        aid = paper.get("arxiv_id") or ""
        url = paper.get("url", "")
        if aid and aid in seen_arxiv_ids:
            continue
        if url and url in seen_urls:
            continue
        if aid:
            seen_arxiv_ids.add(aid)
        if url:
            seen_urls.add(url)
        combined.append(paper)

    for hit in searxng_results:
        url = hit.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        combined.append(hit)

    # ── Step 4：用 arXiv API 批量补充 metadata ───────────────────────
    enriched = enrich_search_results_with_arxiv(combined)

    # ── Step 5：最终去重 ──────────────────────────────────────────────
    final_candidates: list[dict] = []
    final_seen: set[str] = set()
    for cand in enriched:
        aid = cand.get("arxiv_id") or ""
        url = cand.get("url", "")
        key = aid or url or cand.get("title", "")
        if key and key not in final_seen:
            final_seen.add(key)
            final_candidates.append(cand)

    # ── Step 6：构建 RagResult ────────────────────────────────────────
    total = len(searxng_results) + len(arxiv_direct_results) + len(deepxiv_results)
    unique = len(final_candidates)

    rag_result = RagResult(
        query=plan_goal,
        sub_questions=(brief or {}).get("sub_questions", []) if brief else [],
        rag_strategy="searxng_broad + arxiv_direct_precision + deepxiv_trending + arxiv_api_enrich",
        paper_candidates=final_candidates,
        evidence_chunks=[],
        retrieval_trace=query_traces,
        dedup_log=[{"strategy": "arxiv_id+url dedup", "total": total, "unique": unique}],
        rerank_log=[],
        coverage_notes=[
            f"执行 {len(all_queries)} 个查询，"
            f"SearXNG {len(searxng_results)} 条 + arXiv API {len(arxiv_direct_results)} 条 + DeepXiv {len(deepxiv_results)} 条，"
            f"去重后 {unique} 篇"
        ],
        total_papers=unique,
        total_chunks=0,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )

    # ── Step 6：将搜索结果 ingest 进本地向量库（供后续调研/report 生成使用）───────
    _ingest_paper_candidates(final_candidates, workspace_id=state.get("workspace_id"))

    logger.info(
        "[search_node] done: %d queries → %d hits → %d unique papers",
        len(all_queries), total, unique,
    )
    return {"rag_result": rag_result}


def _ingest_paper_candidates(
    candidates: list[dict],
    *,
    workspace_id: str | None = None,
    top_n: int = 50,
) -> None:
    """将搜索到的论文 abstract 作为 coarse chunks 写入 PostgreSQL。

    写入内容：title + abstract 拼接作为 chunk text，section = "abstract"。
    目的：后续调研/报告生成时，rag_search 能召回本次调研找到的论文。
    注意：不下载 PDF，仅存 metadata + abstract，轻量写入。
    """
    import hashlib

    if not candidates:
        return

    to_ingest = candidates[:top_n]

    try:
        from src.db.engine import get_session_factory
        from src.corpus.store.chunk_store import ChunkStore
        from src.db.models import Document, CoarseChunk as ORMCoarseChunk

        session_factory = get_session_factory()
        session = session_factory()
        try:
            for cand in to_ingest:
                title = str(cand.get("title") or "")
                abstract = str(cand.get("abstract") or cand.get("summary") or "")
                if not title and not abstract:
                    continue

                arxiv_id = str(cand.get("arxiv_id") or "")
                url = str(cand.get("url") or "")
                if arxiv_id:
                    doc_id = f"arxiv:{arxiv_id}"
                elif url:
                    doc_id = hashlib.md5(url.encode()).hexdigest()[:24]
                else:
                    doc_id = hashlib.md5(title[:200].encode()).hexdigest()[:24]

                chunk_text = (title + "\n\n" + abstract).strip()
                chunk_id = hashlib.sha256(
                    f"{doc_id}:abstract:0".encode()
                ).hexdigest()[:24]

                # upsert Document
                orm_doc = session.query(Document).filter(Document.doc_id == doc_id).first()
                if orm_doc is None:
                    orm_doc = Document(
                        doc_id=doc_id,
                        title=title[:500],
                        source_uri=url or f"arxiv:{arxiv_id}" if arxiv_id else "",
                        paper_type="unknown",
                    )
                    session.merge(orm_doc)

                # upsert CoarseChunk
                orm_chunk = ORMCoarseChunk(
                    coarse_chunk_id=chunk_id,
                    doc_id=doc_id,
                    canonical_id=doc_id,
                    section="abstract",
                    section_level=1,
                    page_start=1,
                    page_end=1,
                    char_start=0,
                    char_end=len(chunk_text),
                    text=chunk_text,
                    text_hash=hashlib.md5(chunk_text.encode()).hexdigest(),
                    token_count=int(len(chunk_text) * 0.25),
                    order_idx=0,
                    meta_info={
                        "workspace_id": workspace_id,
                        "source": "search_node_ingest",
                        "arxiv_id": arxiv_id,
                        "year": str(cand.get("year") or ""),
                        "authors": str(cand.get("authors") or ""),
                    },
                )
                session.merge(orm_chunk)

            session.commit()
            logger.info(
                "[search_node] ingested %d/%d papers into local corpus (workspace=%s)",
                len(to_ingest), len(candidates), workspace_id,
            )
        except Exception as e:
            session.rollback()
            logger.warning("[search_node] failed to ingest papers: %s", e)
        finally:
            session.close()
    except Exception as e:
        logger.warning("[search_node] ingest skipped (DB not available): %s", e)


def _run_deepxiv_queries(
    all_queries: list[tuple[str, str, int]],
    year_filter: str | None = None,
) -> list[dict]:
    """
    通过 DeepXiv 执行关键词搜索，发现 SearXNG/arXiv API 可能遗漏的相关论文。

    策略（参考 DeepXiv 设计）：
    1. 取前 3 个核心查询词在 DeepXiv 搜索（每词最多 10 篇）
    2. 同时追加 trending 热门论文（7 天内最多 15 篇）
    3. DeepXiv 结果与现有结果去重后返回

    注意：DeepXiv 提供 TLDR + keywords，比 raw abstract 信息更丰富，
    可在 extract_node 中直接用 brief 信息。
    """
    from src.tools.deepxiv_client import search_papers, get_trending_papers

    results: list[dict] = []
    seen_ids: set[str] = set()

    # DeepXiv 有每日请求限额，最多搜 3 个查询词
    core_queries = [q for q, _, _ in all_queries[:3]]

    for q in core_queries:
        try:
            papers = search_papers(q, size=10)
            for paper in papers:
                aid = paper.get("arxiv_id") or ""
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    results.append(paper)
        except Exception as e:
            logger.warning("[search_node] DeepXiv search(%r) failed: %s", q, e)

    # 追加 trending 热门论文（按热度发现，不依赖关键词匹配）
    try:
        days_back = 90
        if year_filter:
            try:
                yf = int(year_filter)
                from datetime import datetime, timezone
                y_now = datetime.now(timezone.utc).year
                days_back = min((y_now - yf) * 365, 365)
            except Exception:
                pass

        trending = get_trending_papers(days=int(days_back // 7), size=15)
        for paper in trending:
            aid = paper.get("arxiv_id") or ""
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                results.append(paper)
    except Exception as e:
        logger.warning("[search_node] DeepXiv trending failed: %s", e)

    logger.info("[search_node] DeepXiv: %d papers from queries + trending", len(results))
    return results


def _time_filter_from_range(time_range: str | None) -> str | None:
    """将 time_range 字符串转换为 arXiv API 的年份格式。"""
    if not time_range:
        return None
    import re
    now = datetime.now(timezone.utc).year
    if "近2年" in time_range or "2年" in time_range:
        return str(now - 2)
    if "近1年" in time_range or "1年" in time_range:
        return str(now - 1)
    if "近3年" in time_range or "3年" in time_range:
        return str(now - 3)
    m = re.search(r"20\d{2}", time_range)
    if m:
        return m.group(0)
    return None

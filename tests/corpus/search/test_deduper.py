"""PaperDeduper 单元测试。"""
from __future__ import annotations

import pytest

from src.corpus.search.deduper import (
    PaperDeduper,
    DedupedCandidate,
    DedupInfo,
)
from src.corpus.search.retrievers.models import (
    MergedCandidate,
    RecallEvidence,
    RetrievalPath,
    MatchedQuery,
)


def make_recall_evidence(doc_id: str, path: RetrievalPath, score: float = 0.8) -> RecallEvidence:
    return RecallEvidence(
        chunk_id=f"chunk-{doc_id}",
        doc_id=doc_id,
        canonical_id=doc_id.split("-")[0],
        section="abstract",
        text=f"Text for {doc_id}",
        score=score,
        path=path,
    )


def make_matched_query(doc_id: str, query: str, path: RetrievalPath) -> MatchedQuery:
    return MatchedQuery(
        query_text=query,
        path=path,
        rank=1,
        score=0.9,
        is_main_query=True,
    )


def make_candidate(
    doc_id: str,
    canonical_id: str,
    title: str,
    rrf_score: float = 1.0,
    path: RetrievalPath = RetrievalPath.KEYWORD_TITLE,
    matched_query: str = "test query",
) -> MergedCandidate:
    c = MergedCandidate(
        doc_id=doc_id,
        canonical_id=canonical_id,
        title=title,
        abstract=f"Abstract for {title}",
        authors=["Author A"],
        year=2023,
        venue="ICML",
        source_uri=f"https://arxiv.org/abs/{doc_id}",
        rrf_score=rrf_score,
        keyword_score=0.5,
        dense_score=0.3,
    )
    c.recall_evidence = [make_recall_evidence(doc_id, path)]
    c.matched_queries = [make_matched_query(doc_id, matched_query, path)]
    return c


class TestPaperDeduperDedup:
    """dedup() 核心逻辑测试。"""

    def test_dedup_merge_same_canonical_id(self):
        """同一 canonical_id 的多条候选应被归并为一条。"""
        c1 = make_candidate("doc-1-v1", "canon-1", "Multi-Agent Survey", rrf_score=1.5)
        c2 = make_candidate("doc-1-arxiv", "canon-1", "Multi-Agent Survey", rrf_score=0.8)
        c3 = make_candidate("doc-2", "canon-2", "Another Paper", rrf_score=1.0)

        deduper = PaperDeduper()
        result = deduper.dedup([c1, c2, c3])

        # 应该归并成 2 条（canon-1 合并，canon-2 独立）
        assert len(result) == 2

        # 找到 canon-1 的那条
        canon1 = next(r for r in result if r.canonical_id == "canon-1")
        # 主候选应为 rrf_score 最高的 doc-1-v1
        assert canon1.primary_doc_id == "doc-1-v1"
        # merged_doc_ids 应包含两条
        assert "doc-1-v1" in canon1.merged_doc_ids
        assert "doc-1-arxiv" in canon1.merged_doc_ids
        # dedup_info 应包含被归并的 id
        assert "doc-1-arxiv" in canon1.dedup_info.merged_doc_ids

    def test_dedup_without_canonical_id(self):
        """无 canonical_id 时按 doc_id 去重。"""
        c1 = make_candidate("doc-1", None, "Paper One", rrf_score=1.0)
        c2 = make_candidate("doc-2", None, "Paper Two", rrf_score=0.8)

        deduper = PaperDeduper()
        result = deduper.dedup([c1, c2])

        assert len(result) == 2

    def test_dedup_highest_rrf_is_primary(self):
        """RRF 分数最高的候选应被选为主候选。"""
        c_low = make_candidate("doc-1-pdf", "canon-1", "Survey", rrf_score=0.3)
        c_high = make_candidate("doc-1-arxiv", "canon-1", "Survey", rrf_score=1.5)

        deduper = PaperDeduper()
        result = deduper.dedup([c_low, c_high])

        assert len(result) == 1
        assert result[0].primary_doc_id == "doc-1-arxiv"
        assert result[0].title == "Survey"

    def test_dedup_aggregates_scores(self):
        """去重后各路分数应取各路最高值。"""
        c1 = MergedCandidate(
            doc_id="doc-1-pdf", canonical_id="canon-1",
            title="Paper", rrf_score=1.0, keyword_score=0.1, dense_score=0.8,
        )
        c2 = MergedCandidate(
            doc_id="doc-1-arxiv", canonical_id="canon-1",
            title="Paper", rrf_score=0.8, keyword_score=0.9, dense_score=0.2,
        )

        deduper = PaperDeduper()
        result = deduper.dedup([c1, c2])

        assert len(result) == 1
        assert result[0].keyword_score == 0.9   # max(0.1, 0.9)
        assert result[0].dense_score == 0.8     # max(0.8, 0.2)

    def test_dedup_collects_all_sources(self):
        """去重后应收集所有来源。"""
        c1 = MergedCandidate(
            doc_id="doc-1-pdf", canonical_id="canon-1",
            title="Paper", rrf_score=1.0, source_uri="file://doc-1.pdf",
        )
        c2 = MergedCandidate(
            doc_id="doc-1-arxiv", canonical_id="canon-1",
            title="Paper", rrf_score=0.8, source_uri="https://arxiv.org/abs/doc-1",
        )

        deduper = PaperDeduper()
        result = deduper.dedup([c1, c2])

        assert "file://doc-1.pdf" in result[0].dedup_info.source_refs
        assert "https://arxiv.org/abs/doc-1" in result[0].dedup_info.source_refs

    def test_dedup_empty_input(self):
        """空输入应返回空列表。"""
        deduper = PaperDeduper()
        result = deduper.dedup([])
        assert result == []

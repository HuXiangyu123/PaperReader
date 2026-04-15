"""CandidateBuilder 单元测试。"""
from __future__ import annotations

import pytest

from src.corpus.search.candidate_builder import (
    CandidateBuilder,
    PaperCandidate,
    ScoreBreakdown,
)
from src.corpus.search.deduper import DedupedCandidate, DedupInfo


def _make_deduped(
    doc_id: str,
    canonical_id: str,
    title: str = "Test Paper",
    rrf_score: float = 0.5,
    rerank_score: float | None = None,
) -> DedupedCandidate:
    """构建测试用 DedupedCandidate。"""
    c = DedupedCandidate(
        canonical_id=canonical_id,
        primary_doc_id=doc_id,
        title=title,
        rrf_score=rrf_score,
        keyword_score=0.3,
        dense_score=0.4,
        dedup_info=DedupInfo(
            is_canonical_representative=True,
            merged_doc_ids=[],
            source_refs=[f"https://example.com/{doc_id}"],
        ),
    )
    c.rerank_score = rerank_score
    if rerank_score is not None:
        c.final_score = rrf_score * 0.4 + rerank_score * 0.6
    else:
        c.final_score = rrf_score
    return c


def test_build_returns_paper_candidates():
    """build() 返回 PaperCandidate 列表。"""
    c1 = _make_deduped("doc-1", "canon-1", rrf_score=0.5)
    c2 = _make_deduped("doc-2", "canon-2", rrf_score=0.8)
    builder = CandidateBuilder()
    result = builder.build([c1, c2], top_k=2)
    assert len(result) == 2
    assert all(isinstance(pc, PaperCandidate) for pc in result)


def test_build_respects_top_k():
    """build() 遵守 top_k 限制。"""
    candidates = [
        _make_deduped(f"doc-{i}", f"canon-{i}", rrf_score=1.0 - i * 0.1)
        for i in range(10)
    ]
    builder = CandidateBuilder()
    result = builder.build(candidates, top_k=3)
    assert len(result) == 3


def test_build_sorted_by_final_score():
    """结果按 final_score 降序排列。"""
    c1 = _make_deduped("doc-1", "canon-1", rrf_score=0.5, rerank_score=0.9)
    c2 = _make_deduped("doc-2", "canon-2", rrf_score=0.8, rerank_score=0.2)
    builder = CandidateBuilder()
    result = builder.build([c1, c2], top_k=2)
    assert result[0].paper_id == "doc-1"  # rerank 更高的在前


def test_build_score_breakdown():
    """分数明细正确传递。"""
    c = _make_deduped("doc-1", "canon-1", rrf_score=0.6, rerank_score=0.8)
    builder = CandidateBuilder()
    result = builder.build([c], top_k=1)
    assert result[0].scores.rrf_score == 0.6
    assert result[0].scores.rerank_score == 0.8
    assert result[0].scores.final_score > 0


def test_build_why_retrieved():
    """why_retrieved 字段有内容。"""
    c = _make_deduped("doc-1", "canon-1", rrf_score=0.5)
    builder = CandidateBuilder()
    result = builder.build([c], top_k=1)
    assert result[0].why_retrieved != ""
    assert "RRF" in result[0].why_retrieved


def test_build_empty_input():
    """空输入返回空列表。"""
    builder = CandidateBuilder()
    result = builder.build([], top_k=5)
    assert result == []

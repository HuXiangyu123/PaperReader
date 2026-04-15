"""Corpus Search API 测试。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.routes.corpus_search import (
    CorpusSearchRequest,
    SearchFilters,
    CorpusSearchResponse,
    MergedCandidateResponse,
    RetrievalTraceResponse,
)


def test_search_filters_model():
    """SearchFilters 验证。"""
    f = SearchFilters(year_range=(2020, 2025), source_type=["arxiv"])
    assert f.year_range == (2020, 2025)
    assert f.source_type == ["arxiv"]


def test_corpus_search_request_valid():
    """正常请求体验证。"""
    req = CorpusSearchRequest(query="multi-agent systems")
    assert req.query == "multi-agent systems"
    assert req.sub_questions == []
    assert req.top_k == 100
    assert req.recall_top_k == 100
    assert req.filters is None


def test_corpus_search_request_with_filters():
    """带过滤条件的请求。"""
    req = CorpusSearchRequest(
        query="retrieval",
        filters=SearchFilters(year_range=(2020, 2025), source_type=["arxiv"]),
    )
    assert req.filters.year_range == (2020, 2025)
    assert req.filters.source_type == ["arxiv"]


def test_corpus_search_request_validation_empty_query():
    """空 query 应抛出验证错误。"""
    with pytest.raises(ValidationError):
        CorpusSearchRequest(query="")


def test_corpus_search_request_validation_top_k_bounds():
    """top_k 超出范围应抛出验证错误。"""
    with pytest.raises(ValidationError):
        CorpusSearchRequest(query="test", top_k=1000)


def test_corpus_search_request_recall_top_k_bounds():
    """recall_top_k 超出范围应抛出验证错误。"""
    with pytest.raises(ValidationError):
        CorpusSearchRequest(query="test", recall_top_k=0)


def test_corpus_search_request_with_sub_questions():
    """带子问题的请求。"""
    req = CorpusSearchRequest(
        query="multi-agent systems",
        sub_questions=["agent coordination", "communication protocols"],
    )
    assert len(req.sub_questions) == 2
    assert req.sub_questions[0] == "agent coordination"


def test_corpus_search_response_model():
    """响应模型验证。"""
    resp = CorpusSearchResponse(
        candidates=[],
        trace=[],
        total_candidates=0,
        merged_count=0,
        duration_ms=42.5,
    )
    assert resp.total_candidates == 0
    assert resp.duration_ms == 42.5


def test_merged_candidate_response_model():
    """候选论文响应模型。"""
    cand = MergedCandidateResponse(
        doc_id="doc-123",
        canonical_id="canon-456",
        title="Test Paper",
        authors="John Doe, Jane Smith",
        year=2023,
        venue="ICML",
        rrf_score=0.85,
        keyword_score=0.9,
        dense_score=0.8,
    )
    assert cand.doc_id == "doc-123"
    assert cand.title == "Test Paper"
    assert cand.rrf_score == 0.85


def test_retrieval_trace_response_model():
    """检索轨迹响应模型。"""
    trace = RetrievalTraceResponse(
        query="test query",
        sub_question_id="sq-0",
        retrieval_path="keyword_coarse",
        target_index="coarse",
        filter_summary="year: 2020-2025",
        top_k_requested=100,
        returned_doc_ids=["doc-1", "doc-2"],
        returned_chunk_ids=["chunk-1", "chunk-2"],
        returned_count=2,
        duration_ms=15.3,
    )
    assert trace.query == "test query"
    assert trace.returned_count == 2

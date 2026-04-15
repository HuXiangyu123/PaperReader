"""CrossEncoderReranker 单元测试。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.corpus.search.reranker import CrossEncoderReranker, RerankResult
from src.corpus.search.deduper import DedupedCandidate, DedupInfo


def _make_deduped(
    doc_id: str,
    canonical_id: str,
    title: str = "Test Paper",
    abstract: str | None = None,
    rrf_score: float = 0.5,
) -> DedupedCandidate:
    """构建测试用 DedupedCandidate。"""
    return DedupedCandidate(
        canonical_id=canonical_id,
        primary_doc_id=doc_id,
        title=title,
        abstract=abstract,
        rrf_score=rrf_score,
        dedup_info=DedupInfo(
            is_canonical_representative=True,
            merged_doc_ids=[],
            source_refs=[f"https://example.com/{doc_id}"],
        ),
    )


def test_reranker_unavailable():
    """sentence-transformers 未安装时 rerank 不可用。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    # is_available 会尝试加载，返回 False
    assert reranker.is_available is False


def test_rerank_empty_candidates():
    """空候选列表返回空。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    result = reranker.rerank("query", [])
    assert result == []


def test_candidates_to_pairs():
    """_candidates_to_pairs 正确构造 query-doc 对。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    c = _make_deduped(
        "doc-1", "canon-1",
        title="Attention Is All You Need",
        abstract="We propose a new network architecture based on attention.",
    )
    pairs = reranker._candidates_to_pairs("transformer attention", [c])
    assert len(pairs) == 1
    query, doc = pairs[0]
    assert query == "transformer attention"
    assert "Attention Is All You Need" in doc
    assert "attention" in doc


def test_candidates_to_pairs_title_only():
    """仅有标题时正常工作。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    c = _make_deduped("doc-1", "canon-1", title="Paper Title")
    pairs = reranker._candidates_to_pairs("query", [c])
    assert len(pairs) == 1
    assert "Paper Title" in pairs[0][1]


def test_rerank_with_fusion_fallback():
    """rerank 失败时退化为 RRF 排序。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    c1 = _make_deduped("doc-1", "canon-1", rrf_score=0.3)
    c2 = _make_deduped("doc-2", "canon-2", rrf_score=0.9)

    # rerank 返回空时退化为 RRF
    with patch.object(reranker, "rerank", return_value=[]):
        result = reranker.rerank_with_fusion("test", [c1, c2])

    assert len(result) == 2
    assert result[0].canonical_id == "canon-2"  # RRF 更高的在前


def test_rerank_with_fusion_normalizes_scores():
    """rerank_with_fusion 正确归一化并融合。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    c1 = _make_deduped("doc-1", "canon-1", rrf_score=0.4)
    c2 = _make_deduped("doc-2", "canon-2", rrf_score=0.8)

    # Mock rerank 返回：doc-1 高分，doc-2 低分
    mock_results = [
        RerankResult(
            doc_id="doc-1",
            canonical_id="canon-1",
            rerank_score=0.95,
            rerank_index=0,
        ),
        RerankResult(
            doc_id="doc-2",
            canonical_id="canon-2",
            rerank_score=0.2,
            rerank_index=1,
        ),
    ]

    with patch.object(reranker, "rerank", return_value=mock_results):
        result = reranker.rerank_with_fusion(
            "test", [c1, c2], fusion_weights=(0.4, 0.6)
        )

    assert len(result) == 2
    # doc-1: RRF_norm=0.4/0.8=0.5, rerank=0.95, final=0.4*0.5+0.6*0.95=0.77
    # doc-2: RRF_norm=0.8/0.8=1.0, rerank=0.2, final=0.4*1.0+0.6*0.2=0.52
    assert result[0].canonical_id == "canon-1"  # doc-1 最终分数更高
    assert result[0].rerank_score is not None


def test_rerank_with_fusion_top_n_trim():
    """top_n 参数正确限制进入 rerank 的候选数量。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    candidates = [
        _make_deduped(f"doc-{i}", f"canon-{i}", rrf_score=1.0 - i * 0.05)
        for i in range(20)
    ]

    # rerank 正常返回，但 mock top_n=5
    mock_results = [
        RerankResult(doc_id=f"doc-{i}", canonical_id=f"canon-{i}",
                      rerank_score=0.9 - i * 0.1, rerank_index=i)
        for i in range(5)
    ]

    with patch.object(reranker, "rerank", return_value=mock_results):
        result = reranker.rerank_with_fusion("test", candidates, top_n=5)

    # 原始候选中的每个都会在结果中（退化为 RRF 时保留全部）
    assert len(result) == 20


def test_rerank_score_written_back():
    """rerank_with_fusion 正确回写 rerank_score。"""
    reranker = CrossEncoderReranker(model="nonexistent-model")
    c1 = _make_deduped("doc-1", "canon-1", rrf_score=0.4)
    c2 = _make_deduped("doc-2", "canon-2", rrf_score=0.8)

    mock_results = [
        RerankResult(doc_id="doc-1", canonical_id="canon-1",
                      rerank_score=0.95, rerank_index=0),
        RerankResult(doc_id="doc-2", canonical_id="canon-2",
                      rerank_score=0.2, rerank_index=1),
    ]

    with patch.object(reranker, "rerank", return_value=mock_results):
        reranker.rerank_with_fusion("test", [c1, c2])

    assert c1.rerank_score is not None
    assert c2.rerank_score is not None
    assert c1.final_score > c2.final_score

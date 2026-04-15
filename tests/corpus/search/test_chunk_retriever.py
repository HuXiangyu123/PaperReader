"""ChunkRetriever 单元测试。"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.corpus.search.retrievers.chunk_retriever import ChunkRetriever
from src.corpus.search.models import EvidenceChunk


class MockChunk:
    """模拟 FineChunk。"""
    def __init__(
        self,
        chunk_id: str,
        doc_id: str,
        text: str,
        section: str = "",
        page_start: int = 1,
        page_end: int = 1,
    ):
        self.chunk_id = chunk_id
        self.doc_id = doc_id
        self.text = text
        self.section = section
        self.page_start = page_start
        self.page_end = page_end
        self.canonical_id = doc_id


class TestChunkRetriever:
    """ChunkRetriever 测试。"""

    def test_retrieve_empty_paper_ids(self):
        """空 paper_ids 返回空。"""
        retriever = ChunkRetriever()
        result = retriever.retrieve(paper_ids=[], query="test")
        assert result == []

    def test_rrf_merge_no_dense(self):
        """无 dense 路径时只靠 keyword 结果排序。"""
        retriever = ChunkRetriever()
        k_results = [
            EvidenceChunk(chunk_id="c1", paper_id="p1", text="test", keyword_score=0.9),
            EvidenceChunk(chunk_id="c2", paper_id="p1", text="test2", keyword_score=0.7),
        ]
        merged = retriever._rrf_merge(k_results, [])
        assert len(merged) == 2
        assert merged[0].chunk_id == "c1"  # keyword 分数更高
        assert merged[0].chunk_path == "keyword"

    def test_rrf_merge_with_dense(self):
        """RRF 正确合并 keyword 和 dense 结果。"""
        retriever = ChunkRetriever()
        k_results = [
            EvidenceChunk(chunk_id="c1", paper_id="p1", text="test", keyword_score=0.9),
        ]
        d_results = [
            EvidenceChunk(chunk_id="c2", paper_id="p1", text="test2", dense_score=0.8),
        ]
        merged = retriever._rrf_merge(k_results, d_results)
        assert len(merged) == 2
        # c1 只在 keyword，c2 只在 dense，各自保留路径
        assert merged[0].chunk_path in ("keyword", "dense")

    def test_rrf_merge_hybrid(self):
        """同一 chunk 在两路都出现时标记为 hybrid。"""
        retriever = ChunkRetriever()
        k_results = [
            EvidenceChunk(chunk_id="c1", paper_id="p1", text="test", keyword_score=0.5),
        ]
        d_results = [
            EvidenceChunk(chunk_id="c1", paper_id="p1", text="test", dense_score=0.5),
        ]
        merged = retriever._rrf_merge(k_results, d_results)
        assert len(merged) == 1
        assert merged[0].chunk_path == "hybrid"
        assert merged[0].rrf_score > 0

    def test_filter_chunks(self):
        """过滤太短和太长的 chunks。"""
        retriever = ChunkRetriever()
        chunks = [
            EvidenceChunk(chunk_id="c1", paper_id="p1", text="A" * 30),     # 30 chars — 略过
            EvidenceChunk(chunk_id="c2", paper_id="p1", text="B" * 200),    # OK
            EvidenceChunk(chunk_id="c3", paper_id="p1", text="C" * 5000),  # 过长
            EvidenceChunk(chunk_id="c4", paper_id="p1", text="D" * 100),    # OK
        ]
        filtered = retriever._filter_chunks(chunks, min_text_len=50, max_text_len=2000)
        ids = [r.chunk_id for r in filtered]
        assert "c1" not in ids   # 太短
        assert "c2" in ids
        assert "c3" not in ids   # 过长
        assert "c4" in ids

    def test_chunk_to_result(self):
        """_chunk_to_result 正确转换并设置 scores。"""
        retriever = ChunkRetriever()
        chunk = MockChunk(
            chunk_id="ck-1",
            doc_id="doc-1",
            text="This is the method description.",
            section="Proposed Method",
            page_start=3,
            page_end=5,
        )
        result = retriever._chunk_to_result(chunk, keyword_score=0.8, dense_score=0.6)
        assert result.chunk_id == "ck-1"
        assert result.paper_id == "doc-1"
        assert result.section == "Proposed Method"
        # 由于 __post_init__ 的同步逻辑，分数存储在 scores 属性中
        assert result.scores.keyword_score == 0.8
        assert result.scores.dense_score == 0.6

    def test_determine_path_keyword_only(self):
        """_determine_path: 仅 keyword 路径。"""
        retriever = ChunkRetriever()
        path = retriever._determine_path("c1", {"c1": 1, "c2": 2}, {})
        assert path == "keyword"

    def test_determine_path_dense_only(self):
        """_determine_path: 仅 dense 路径。"""
        retriever = ChunkRetriever()
        path = retriever._determine_path("c1", {}, {"c1": 1})
        assert path == "dense"

    def test_determine_path_hybrid(self):
        """_determine_path: hybrid 路径。"""
        retriever = ChunkRetriever()
        path = retriever._determine_path("c1", {"c1": 1}, {"c1": 1})
        assert path == "hybrid"

    def test_collect_chunks_no_store(self):
        """无 chunk_store 时返回空列表。"""
        retriever = ChunkRetriever(chunk_store=None)
        chunks = retriever._collect_chunks(["doc-1"])
        assert chunks == []

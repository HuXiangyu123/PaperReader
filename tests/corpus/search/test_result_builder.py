"""RagResultBuilder 单元测试。"""
from __future__ import annotations

import pytest

from src.corpus.search.result_builder import RagResultBuilder


class MockChunk:
    """模拟 EvidenceChunk。"""
    def __init__(self, support_type: str = "method"):
        self.support_type = support_type
        self.chunk_id = "mock-chunk"


class TestRagResultBuilder:
    """RagResultBuilder 测试。"""

    def test_minimal_build(self):
        """最简调用能生成 RagResult。"""
        builder = RagResultBuilder()
        result = builder.build()
        assert result is not None
        assert result.query == ""
        assert result.total_chunks == 0

    def test_with_query(self):
        """with_query 正确传递。"""
        builder = RagResultBuilder()
        result = builder.with_query("test query").build()
        assert result.query == "test query"

    def test_with_sub_questions(self):
        """with_sub_questions 正确传递。"""
        builder = RagResultBuilder()
        result = builder.with_sub_questions(["q1", "q2"]).build()
        assert result.sub_questions == ["q1", "q2"]

    def test_coverage_note_no_chunks(self):
        """无 chunks 时生成 WARNING。"""
        builder = RagResultBuilder()
        result = builder.with_evidence_chunks([]).build()
        assert any("WARNING" in note for note in result.coverage_notes)

    def test_coverage_note_missing_method(self):
        """缺少 method 类型时生成 NOTE。"""
        builder = RagResultBuilder()
        chunks = [MockChunk(support_type="result")]
        result = builder.with_evidence_chunks(chunks).build()
        assert any("method" in note for note in result.coverage_notes)

    def test_coverage_note_missing_result(self):
        """缺少 result 类型时生成 NOTE。"""
        builder = RagResultBuilder()
        chunks = [MockChunk(support_type="method")]
        result = builder.with_evidence_chunks(chunks).build()
        assert any("result" in note for note in result.coverage_notes)

    def test_coverage_note_insufficient_chunks(self):
        """chunks 过少时生成 NOTE。"""
        builder = RagResultBuilder()
        chunks = [MockChunk() for _ in range(3)]
        result = builder.with_evidence_chunks(chunks).build()
        assert any("较少" in note or "不足" in note for note in result.coverage_notes)

    def test_total_chunks_counted(self):
        """total_chunks 正确统计。"""
        builder = RagResultBuilder()
        chunks = [MockChunk() for _ in range(7)]
        result = builder.with_evidence_chunks(chunks).build()
        assert result.total_chunks == 7

    def test_retrieved_at_iso_format(self):
        """retrieved_at 是 ISO 格式字符串。"""
        builder = RagResultBuilder()
        result = builder.build()
        assert result.retrieved_at != ""
        assert "T" in result.retrieved_at  # ISO format contains T

    def test_fluent_interface(self):
        """支持链式调用。"""
        builder = RagResultBuilder()
        result = (
            builder
            .with_query("test")
            .with_sub_questions(["sq1"])
            .with_rag_strategy("custom-strategy")
            .build()
        )
        assert result.query == "test"
        assert result.sub_questions == ["sq1"]
        assert result.rag_strategy == "custom-strategy"

    def test_with_paper_candidates(self):
        """with_paper_candidates 正确传递。"""
        builder = RagResultBuilder()
        candidates = [{"paper_id": "p1"}, {"paper_id": "p2"}]
        result = builder.with_paper_candidates(candidates).build()
        assert result.total_papers == 2
        assert len(result.paper_candidates) == 2

    def test_with_traces(self):
        """with_traces 正确传递。"""
        builder = RagResultBuilder()
        traces = [{"stage": "search", "time_ms": 100}]
        result = builder.with_traces(traces).build()
        assert len(result.retrieval_trace) == 1

    def test_with_dedup_logs(self):
        """with_dedup_logs 正确传递。"""
        builder = RagResultBuilder()
        logs = [{"deduped_count": 5}]
        result = builder.with_dedup_logs(logs).build()
        assert len(result.dedup_log) == 1

    def test_with_rerank_logs(self):
        """with_rerank_logs 正确传递。"""
        builder = RagResultBuilder()
        logs = [{"stage": "paper_rerank", "candidates_count": 10}]
        result = builder.with_rerank_logs(logs).build()
        assert len(result.rerank_log) == 1

    def test_default_rag_strategy(self):
        """默认 rag_strategy 正确设置。"""
        builder = RagResultBuilder()
        result = builder.build()
        assert result.rag_strategy == "keyword+dense+rrf+evidence_typing"

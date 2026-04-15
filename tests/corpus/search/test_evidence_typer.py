"""EvidenceTyper 单元测试。"""
from __future__ import annotations

import pytest

from src.corpus.search.evidence_typer import EvidenceTyper, SUPPORT_TYPE_KEYWORDS


def _make_mock_chunk(section: str):
    """构建模拟 chunk 对象。"""
    class MockChunk:
        def __init__(self, sec):
            self.section = sec
    return MockChunk(section)


class TestEvidenceTyper:
    """EvidenceTyper 测试。"""

    def test_method_type(self):
        """测试 method 类型推断。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type("Proposed Method") == "method"
        assert typer.infer_support_type("Methodology") == "method"
        assert typer.infer_support_type("Model Architecture") == "method"
        assert typer.infer_support_type("Algorithm Design") == "method"

    def test_result_type(self):
        """测试 result 类型推断。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type("Experimental Results") == "result"
        assert typer.infer_support_type("Results and Analysis") == "result"
        assert typer.infer_support_type("Performance Evaluation") == "result"
        assert typer.infer_support_type("Benchmark Results") == "result"

    def test_background_type(self):
        """测试 background 类型推断。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type("Introduction") == "background"
        assert typer.infer_support_type("Related Work") == "background"
        assert typer.infer_support_type("Background and Motivation") == "background"

    def test_limitation_type(self):
        """测试 limitation 类型推断。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type("Limitations") == "limitation"
        assert typer.infer_support_type("Weaknesses and Future Work") == "limitation"
        assert typer.infer_support_type("Challenges") == "limitation"

    def test_default_claim_support(self):
        """测试默认类型 claim_support。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type("Abstract") == "claim_support"
        assert typer.infer_support_type("Conclusion") == "claim_support"
        assert typer.infer_support_type("") == "claim_support"
        assert typer.infer_support_type(None) == "claim_support"

    def test_case_insensitive(self):
        """测试大小写不敏感。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type("EXPERIMENTAL RESULTS") == "result"
        assert typer.infer_support_type("Proposed METHOD") == "method"

    def test_type_chunk(self):
        """测试 type_chunk 方法。"""
        typer = EvidenceTyper()
        chunk = _make_mock_chunk("Experimental Results")
        assert typer.type_chunk(chunk) == "result"

    def test_type_chunks_batch(self):
        """测试 type_chunks 批量处理。"""
        typer = EvidenceTyper()
        chunks = [
            _make_mock_chunk("Proposed Method"),
            _make_mock_chunk("Results"),
        ]
        types = typer.type_chunks(chunks)
        assert types == ["method", "result"]

    def test_keywords_coverage(self):
        """确保所有定义的关键词都有对应类型。"""
        typer = EvidenceTyper()
        for stype, keywords in SUPPORT_TYPE_KEYWORDS.items():
            assert stype in ["method", "result", "background", "limitation"]
            for kw in keywords:
                result = typer.infer_support_type(kw.title())
                assert result == stype, f"keyword '{kw}' should map to '{stype}'"

    def test_empty_section(self):
        """测试空 section 返回默认类型。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type("") == "claim_support"

    def test_none_section(self):
        """测试 None section 返回默认类型。"""
        typer = EvidenceTyper()
        assert typer.infer_support_type(None) == "claim_support"

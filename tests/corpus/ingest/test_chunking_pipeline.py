"""Tests for Chunking Pipeline."""

from __future__ import annotations

import pytest

from src.corpus.ingest.chunking_pipeline import ChunkingPipeline, ChunkingResult
from src.corpus.ingest.chunkers import DetectedSection, Paragraph, PaperStructure, StructureDetector
from src.corpus.models import CoarseChunk, FineChunk, PageText, StandardizedDocument


class TestChunkingPipeline:
    """Chunking Pipeline 测试。"""

    def _make_doc(self, text: str) -> tuple[StandardizedDocument, list[PageText]]:
        page = PageText(page_num=1, text=text, char_start=0, char_end=len(text))
        doc = StandardizedDocument(
            doc_id="test_doc",
            workspace_id=None,
            title="Test Paper",
            normalized_text=text,
            canonical_id="canon_test",
        )
        return doc, [page]

    def test_pipeline_basic(self):
        """基本 pipeline 测试。"""
        text = """Abstract
We propose a new method.

Introduction
Deep learning is important.

Methods
We use attention mechanisms.

Conclusion
Results are strong."""

        doc, pages = self._make_doc(text)
        pipeline = ChunkingPipeline()
        result = pipeline.chunk(doc, pages)

        assert result.coarse_count >= 3  # abstract + intro + methods + conclusion
        assert result.fine_count >= result.coarse_count  # fine >= coarse
        assert result.elapsed_ms > 0
        assert isinstance(result.errors, list)

    def test_pipeline_with_empty_text(self):
        """空文本不崩溃。"""
        doc, pages = self._make_doc("")
        pipeline = ChunkingPipeline()
        result = pipeline.chunk(doc, pages)

        assert isinstance(result, ChunkingResult)
        # 允许 0 chunk（后续可扩展警告）

    def test_pipeline_returns_correct_types(self):
        """返回正确的数据类型。"""
        text = """Abstract
Short abstract.
Methods
The methodology described here.
Conclusion
In summary."""

        doc, pages = self._make_doc(text)
        pipeline = ChunkingPipeline()
        result = pipeline.chunk(doc, pages)

        assert all(isinstance(c, CoarseChunk) for c in result.coarse_chunks)
        assert all(isinstance(f, FineChunk) for f in result.fine_chunks)

    def test_pipeline_elapsed_time(self):
        """elapsed_ms 记录正确。"""
        doc, pages = self._make_doc("Abstract\nShort text.\nMethods\nMore details.")
        pipeline = ChunkingPipeline()
        result = pipeline.chunk(doc, pages)
        assert result.elapsed_ms >= 0

    def test_pipeline_section_preserved(self):
        """section 信息保留到 chunk。"""
        text = """Abstract
We propose.

Methods
We use attention."""

        doc, pages = self._make_doc(text)
        pipeline = ChunkingPipeline()
        result = pipeline.chunk(doc, pages)

        assert len(result.coarse_chunks) >= 2
        sections = {c.section for c in result.coarse_chunks}
        assert "abstract" in sections or "introduction" in sections


class TestChunkingResult:
    """ChunkingResult 测试。"""

    def test_result_counts(self):
        """coarse/fine_count 自动计算（通过构造）。"""
        coarse_chunks = [
            CoarseChunk(chunk_id="c1", doc_id="d", canonical_id=None, section="a", order=0),
            CoarseChunk(chunk_id="c2", doc_id="d", canonical_id=None, section="b", order=1),
        ]
        fine_chunks = [
            FineChunk(chunk_id="f1", doc_id="d", canonical_id=None, parent_coarse_chunk_id="c1", section="a", order=0),
            FineChunk(chunk_id="f2", doc_id="d", canonical_id=None, parent_coarse_chunk_id="c1", section="a", order=1),
        ]
        result = ChunkingResult(coarse_chunks=coarse_chunks, fine_chunks=fine_chunks)
        # __post_init__ 在构造时调用，coarse_count/fine_count 自动计算
        assert result.coarse_count == 2
        assert result.fine_count == 2

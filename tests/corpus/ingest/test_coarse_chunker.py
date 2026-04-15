"""Tests for Coarse Chunker."""

from __future__ import annotations

import pytest

from src.corpus.ingest.chunkers import DetectedSection, Paragraph, PaperStructure, StructureDetector
from src.corpus.ingest.coarse_chunker import CoarseChunker
from src.corpus.models import CoarseChunk, PageText, StandardizedDocument


class TestCoarseChunker:
    """Coarse Chunker 测试。"""

    def _make_structure(self, sections_text: dict[str, str]) -> PaperStructure:
        """从 dict 构建 PaperStructure。"""
        sections = []
        char_offset = 0
        page = 1

        for name, text in sections_text.items():
            paragraphs = []
            for line in text.split("\n"):
                if line.strip():
                    paragraphs.append(
                        Paragraph(
                            text=line.strip(),
                            page_start=page,
                            page_end=page,
                            char_start=char_offset,
                            char_end=char_offset + len(line),
                        )
                    )
                    char_offset += len(line) + 1

            sections.append(
                DetectedSection(
                    heading=name,
                    level=1,
                    paragraphs=paragraphs,
                    page_start=1,
                    page_end=1,
                    char_start=0,
                    char_end=char_offset,
                )
            )

        return PaperStructure(
            title="Test Paper",
            abstract=None,
            sections=sections,
            page_boundaries=[0],
        )

    def test_chunk_single_section(self):
        """单章节 → 单个 chunk。"""
        chunker = CoarseChunker()
        structure = self._make_structure({"introduction": "This is a test paragraph."})

        chunks = chunker.chunk(structure, "doc1", "canon1")
        assert len(chunks) >= 1
        assert chunks[0].section == "introduction"
        assert chunks[0].doc_id == "doc1"
        assert chunks[0].canonical_id == "canon1"

    def test_chunk_abstract_isolated(self):
        """abstract 单独成块。"""
        chunker = CoarseChunker()
        structure = self._make_structure({
            "abstract": "This is the abstract with enough content.",
            "introduction": "Introduction paragraph one.",
        })

        chunks = chunker.chunk(structure, "doc1", "canon1")
        abstract_chunks = [c for c in chunks if c.section == "abstract"]
        assert len(abstract_chunks) == 1  # abstract 独立一块

    def test_chunk_conclusion_isolated(self):
        """conclusion 单独成块。"""
        chunker = CoarseChunker()
        structure = self._make_structure({
            "introduction": "Introduction paragraph one.",
            "conclusion": "We have shown that the method works.",
        })

        chunks = chunker.chunk(structure, "doc1", "canon1")
        conclusion_chunks = [c for c in chunks if c.section == "conclusion"]
        assert len(conclusion_chunks) == 1

    def test_chunk_order_sequential(self):
        """chunk order 连续递增。"""
        chunker = CoarseChunker()
        structure = self._make_structure({
            "introduction": "First section content.",
            "methods": "Second section content.",
        })

        chunks = chunker.chunk(structure, "doc1", "canon1")
        orders = [c.order for c in chunks]
        assert orders == sorted(orders)
        assert orders == list(range(len(chunks)))

    def test_chunk_page_info(self):
        """chunk 保留页码信息。"""
        chunker = CoarseChunker()
        structure = self._make_structure({"introduction": "Test content."})

        chunks = chunker.chunk(structure, "doc1", "canon1")
        assert chunks[0].page_start >= 1

    def test_chunk_token_count(self):
        """chunk 自动估算 token 数。"""
        chunker = CoarseChunker()
        long_text = "This is a " + "very " * 100 + "long paragraph text."
        structure = self._make_structure({"methods": long_text})

        chunks = chunker.chunk(structure, "doc1", "canon1")
        for chunk in chunks:
            assert chunk.token_count > 0
            # tokens ≈ chars * 0.25
            assert chunk.token_count < len(chunk.text)

    def test_chunk_empty_structure(self):
        """空 structure 不崩溃。"""
        chunker = CoarseChunker()
        structure = PaperStructure(
            title="Test",
            abstract=None,
            sections=[],
            page_boundaries=[],
        )
        chunks = chunker.chunk(structure, "doc1", "canon1")
        assert chunks == []

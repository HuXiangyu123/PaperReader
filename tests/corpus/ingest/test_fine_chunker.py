"""Tests for Fine Chunker."""

from __future__ import annotations

import pytest

from src.corpus.ingest.chunkers import DetectedSection, Paragraph, PaperStructure
from src.corpus.ingest.coarse_chunker import CoarseChunker
from src.corpus.ingest.fine_chunker import FineChunker, _split_sentences
from src.corpus.models import CoarseChunk


class TestSentenceSplitter:
    """Sentence Splitter 测试。"""

    def test_split_sentences_basic(self):
        """基本句子分割。"""
        text = "We propose the Transformer. It uses self-attention. Results are strong."
        sentences = _split_sentences(text)
        assert len(sentences) == 3
        assert sentences[0] == "We propose the Transformer."
        assert sentences[2] == "Results are strong."

    def test_split_sentences_with_newlines(self):
        """带换行的句子。"""
        text = "First sentence.\n\nSecond sentence."
        sentences = _split_sentences(text)
        assert len(sentences) == 2

    def test_split_sentences_questions(self):
        """问号/感叹号。"""
        text = "Does this work? Yes it does! Great results."
        sentences = _split_sentences(text)
        assert len(sentences) == 3

    def test_split_empty(self):
        """空文本。"""
        assert _split_sentences("") == []
        assert _split_sentences("   ") == []


class TestFineChunker:
    """Fine Chunker 测试。"""

    def _make_coarse_chunks(self) -> list[CoarseChunk]:
        """创建测试用 coarse chunks。"""
        c1 = CoarseChunk(
            chunk_id="coarse1",
            doc_id="doc1",
            canonical_id="canon1",
            section="introduction",
            page_start=1,
            page_end=1,
            char_start=0,
            char_end=200,
            text="First paragraph. Second paragraph. Third paragraph.",
            order=0,
        )
        c2 = CoarseChunk(
            chunk_id="coarse2",
            doc_id="doc1",
            canonical_id="canon1",
            section="methods",
            page_start=2,
            page_end=3,
            char_start=200,
            char_end=500,
            text="We use attention mechanisms. The model architecture is deep. "
            "Training is done with standard optimizer. Results show improvement.",
            order=1,
        )
        return [c1, c2]

    def test_fine_chunker_basic(self):
        """基本功能测试。"""
        chunker = FineChunker()
        coarse = self._make_coarse_chunks()

        fine = chunker.chunk(coarse)

        assert len(fine) >= 2  # 每个 coarse 至少产生 1 个 fine
        # 所有 fine 的 parent 指向有效的 coarse chunk_id
        coarse_ids = {c.chunk_id for c in coarse}
        for f in fine:
            assert f.parent_coarse_chunk_id in coarse_ids
            assert f.doc_id == "doc1"
            assert f.canonical_id == "canon1"

    def test_fine_chunker_short_text(self):
        """过短文本直接作为单个 fine chunk。"""
        chunker = FineChunker()
        short = CoarseChunk(
            chunk_id="coarse_short",
            doc_id="doc1",
            canonical_id="canon1",
            section="abstract",
            page_start=1,
            page_end=1,
            char_start=0,
            char_end=50,
            text="Short text.",
            order=0,
        )
        fine = chunker.chunk([short])
        assert len(fine) == 1
        assert fine[0].text == "Short text."

    def test_fine_order_sequential(self):
        """fine chunk order 连续递增。"""
        chunker = FineChunker()
        coarse = self._make_coarse_chunks()
        fine = chunker.chunk(coarse)

        orders = [f.order for f in fine]
        assert orders == sorted(orders)
        assert orders == list(range(len(fine)))

    def test_fine_chunks_have_parent(self):
        """每个 fine chunk 都有 parent_coarse_chunk_id。"""
        chunker = FineChunker()
        coarse = self._make_coarse_chunks()
        fine = chunker.chunk(coarse)

        for f in fine:
            assert f.parent_coarse_chunk_id
            assert len(f.parent_coarse_chunk_id) > 0

    def test_fine_chunks_preserve_section(self):
        """fine chunk 保留 section 信息。"""
        chunker = FineChunker()
        coarse = self._make_coarse_chunks()
        fine = chunker.chunk(coarse)

        intro_fines = [f for f in fine if f.section == "introduction"]
        assert len(intro_fines) >= 1
        for f in intro_fines:
            assert f.parent_coarse_chunk_id == "coarse1"

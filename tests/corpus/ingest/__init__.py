"""Tests for corpus ingest loaders."""

from __future__ import annotations

import pytest

from src.corpus.ingest.loaders import (
    ArxivSourceInput,
    LocalPdfLoader,
    LocalPdfSourceInput,
    OnlineUrlLoader,
    OnlineUrlSourceInput,
    ArxivLoader,
)


class TestArxivSourceInput:
    def test_arxiv_source_input_create(self):
        inp = ArxivSourceInput(arxiv_id="1706.03762")
        assert inp.arxiv_id == "1706.03762"

    def test_arxiv_source_input_with_version(self):
        inp = ArxivSourceInput(arxiv_id="1706.03762v5")
        assert inp.arxiv_id == "1706.03762v5"


class TestLocalPdfSourceInput:
    def test_local_pdf_source_input(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"dummy")
        inp = LocalPdfSourceInput(file_path=str(pdf))
        assert inp.file_path == str(pdf)


class TestOnlineUrlSourceInput:
    def test_online_url_source_input(self):
        inp = OnlineUrlSourceInput(url="https://example.com/paper.pdf")
        assert inp.url == "https://example.com/paper.pdf"


class TestArxivLoader:
    """ArXiv Loader 测试。"""

    def test_normalize_arxiv_id(self):
        """测试 arXiv ID 规范化。"""
        from src.corpus.ingest.loaders import _normalize_arxiv_id

        assert _normalize_arxiv_id("1706.03762") == "1706.03762"
        assert _normalize_arxiv_id("1706.03762v1") == "1706.03762v1"
        # URL 格式
        assert _normalize_arxiv_id("https://arxiv.org/abs/1706.03762") == "1706.03762"
        assert _normalize_arxiv_id("https://arxiv.org/pdf/1706.03762.pdf") == "1706.03762"

    def test_loader_type_check(self):
        """测试类型检查。"""
        arxiv_loader = ArxivLoader()
        local_loader = LocalPdfLoader()
        online_loader = OnlineUrlLoader()

        with pytest.raises(TypeError):
            arxiv_loader.load(OnlineUrlSourceInput(url="x"))

        with pytest.raises(TypeError):
            local_loader.load(ArxivSourceInput(arxiv_id="x"))

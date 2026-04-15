"""Tests for corpus ingest loaders."""

from __future__ import annotations

import pytest

from src.corpus.ingest.loaders import (
    ArxivLoader,
    ArxivSourceInput,
    LocalPdfLoader,
    LocalPdfSourceInput,
    OnlineUrlLoader,
    OnlineUrlSourceInput,
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

    def test_loader_type_check_arxiv(self):
        """测试 ArxivLoader 类型检查。"""
        loader = ArxivLoader()
        with pytest.raises(TypeError):
            loader.load(OnlineUrlSourceInput(url="x"))
        with pytest.raises(TypeError):
            loader.load(LocalPdfSourceInput(file_path="x.pdf"))

    def test_loader_type_check_local_pdf(self):
        """测试 LocalPdfLoader 类型检查。"""
        loader = LocalPdfLoader()
        with pytest.raises(TypeError):
            loader.load(ArxivSourceInput(arxiv_id="x"))
        with pytest.raises(TypeError):
            loader.load(OnlineUrlSourceInput(url="x"))

    def test_local_pdf_loader_file_not_found(self):
        """测试本地 PDF 文件不存在时抛出异常。"""
        loader = LocalPdfLoader()
        with pytest.raises(FileNotFoundError):
            loader.load(LocalPdfSourceInput(file_path="/nonexistent/path/file.pdf"))

    def test_loader_type_check_online(self):
        """测试 OnlineUrlLoader 类型检查。"""
        loader = OnlineUrlLoader()
        with pytest.raises(TypeError):
            loader.load(ArxivSourceInput(arxiv_id="x"))
        with pytest.raises(TypeError):
            loader.load(LocalPdfSourceInput(file_path="x.pdf"))


class TestExtractArxivIdFromPath:
    def test_extract_arxiv_id(self):
        from src.corpus.ingest.loaders import _extract_arxiv_id_from_path

        assert _extract_arxiv_id_from_path("/path/1706.03762.pdf") == "1706.03762"
        assert _extract_arxiv_id_from_path("/path/1706.03762v3.pdf") == "1706.03762v3"
        assert _extract_arxiv_id_from_path("/path/2301.05678.pdf") == "2301.05678"
        assert _extract_arxiv_id_from_path("/path/random_filename.pdf") is None

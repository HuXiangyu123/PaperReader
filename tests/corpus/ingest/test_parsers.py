"""Tests for corpus ingest parsers."""

from __future__ import annotations

import pytest

from src.corpus.ingest.parsers import (
    HTMLParser,
    MetadataExtractor,
    PDFParser,
)
from src.corpus.models import PageText


class TestPDFParser:
    """PDF Parser 测试。"""

    def test_parse_bytes_invalid(self):
        """测试无效 PDF。"""
        parser = PDFParser()
        page_texts, warnings = parser.parse_bytes(b"not a pdf")
        assert len(page_texts) == 0
        assert len(warnings) > 0

    def test_parse_bytes_truncated(self):
        """测试截断的 PDF 数据。"""
        parser = PDFParser()
        page_texts, warnings = parser.parse_bytes(b"%PDF-1.4 truncated")
        # pypdf 对截断 PDF 会抛出异常或返回空
        assert isinstance(warnings, list)

    def test_estimate_quality_full(self):
        """测试完整元数据的高质量评分。"""
        parser = PDFParser()
        score = parser.estimate_quality(
            "x" * 1000,
            {
                "title": "Attention Is All You Need",
                "abstract": "We propose the Transformer model which relies entirely on attention mechanisms." * 5,
                "arxiv_id": "1706.03762",
            },
        )
        assert score >= 0.9  # 需要 abstract > 50 chars 才触发 +0.15

    def test_estimate_quality_low(self):
        """测试低质量评分（无元数据）。"""
        parser = PDFParser()
        score = parser.estimate_quality("short", {})
        assert score < 0.7

    def test_estimate_quality_medium(self):
        """测试中等质量评分（部分元数据）。"""
        parser = PDFParser()
        score = parser.estimate_quality("x" * 100, {"title": "Some Title"})
        assert 0.5 <= score < 0.9


class TestHTMLParser:
    """HTML Parser 测试。"""

    def test_parse_bytes_basic(self):
        """测试基本 HTML 解析。"""
        parser = HTMLParser()
        html = (
            b"<html><head><title>Test Paper</title></head><body>"
            b"<h1>Attention Is All You Need</h1>"
            b"<p>We propose a novel neural network architecture based entirely "
            b"on attention mechanisms, replacing recurrent layers.</p>"
            b"</body></html>"
        )
        text, warnings = parser.parse_bytes(html)
        assert "Attention Is All You Need" in text
        assert len(warnings) == 0  # 文本足够长，不触发短文本警告

    def test_parse_bytes_strips_scripts(self):
        """测试去除 <script> 标签。"""
        parser = HTMLParser()
        html = b"<html><body><script>alert('x')</script><p>Content</p></body></html>"
        text, warnings = parser.parse_bytes(html)
        assert "alert" not in text
        assert "Content" in text

    def test_parse_bytes_strips_styles(self):
        """测试去除 <style> 标签。"""
        parser = HTMLParser()
        html = b"<html><head><style>.x { color: red }</style></head><body><p>Text</p></body></html>"
        text, warnings = parser.parse_bytes(html)
        assert "color: red" not in text
        assert "Text" in text

    def test_parse_bytes_html_entities(self):
        """测试 HTML 实体还原。"""
        parser = HTMLParser()
        html = b"<html><body><p>Hello&nbsp;World &amp; More &lt;3</p></body></html>"
        text, warnings = parser.parse_bytes(html)
        assert "Hello World" in text or "Hello\u00a0World" in text
        assert "&amp;" not in text
        assert "&lt;" not in text

    def test_parse_bytes_short_warning(self):
        """测试过短 HTML 触发警告。"""
        parser = HTMLParser()
        html = b"<html><body>Hi</body></html>"
        text, warnings = parser.parse_bytes(html)
        assert len(warnings) > 0


class TestMetadataExtractor:
    """Metadata Extractor 测试。"""

    def test_extract_arxiv_metadata(self):
        """测试 arXiv 元数据提取（原始返回，不做 strip，由 normalizer 处理）。"""
        extractor = MetadataExtractor()
        raw = {
            "origin": "arxiv",
            "title": "  Attention Is All You Need  ",
            "authors": ["John Doe", "Jane Smith"],
            "published_year": 2017,
            "abstract": "We propose the Transformer...",
            "arxiv_id": "1706.03762",
        }
        meta = extractor.extract(raw, [])
        # 元数据提取器保留原始格式，strip 由 normalizer 处理
        assert meta["title"].strip() == "Attention Is All You Need"
        assert meta["authors"] == ["John Doe", "Jane Smith"]
        assert meta["year"] == 2017
        assert meta["arxiv_id"] == "1706.03762"
        assert meta["venue"] is None  # arXiv 无 venue

    def test_extract_authors_from_text(self):
        """测试从文本提取作者。"""
        extractor = MetadataExtractor()
        authors = extractor._extract_authors_from_text(
            "John Doe and Jane Smith and Bob Alice\njohn@example.com"
        )
        assert len(authors) > 0
        assert "john@example.com" not in str(authors)

    def test_extract_year_from_text(self):
        """测试从文本提取年份。"""
        extractor = MetadataExtractor()
        year = extractor._extract_year_from_text("Published in 2023 at NeurIPS conference")
        assert year == 2023

    def test_extract_title_from_text(self):
        """测试从文本提取标题。"""
        extractor = MetadataExtractor()
        title = extractor._extract_title_from_text(
            "Attention Is All You Need\nJohn Doe\n2023\njohn@example.com"
        )
        assert "Attention" in title

    def test_extract_abstract_from_text(self):
        """测试从文本提取摘要。"""
        extractor = MetadataExtractor()
        page = PageText(page_num=1, text="Abstract: This paper proposes...", char_start=0, char_end=100)
        abstract = extractor._extract_abstract_from_text([page])
        assert "proposes" in abstract.lower()

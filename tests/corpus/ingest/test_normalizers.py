"""Tests for corpus ingest normalizers."""

from __future__ import annotations

import pytest

from src.corpus.ingest.normalizers import (
    MetadataNormalizer,
    TextNormalizer,
    normalize_venue,
)
from src.corpus.ingest.parsers import MetadataExtractor


class TestTextNormalizer:
    """Text Normalizer 测试。"""

    def test_normalize_whitespace(self):
        """测试空格合并。"""
        normalizer = TextNormalizer()
        text = "Hello    World\n\n\n\nMore"
        result, warnings = normalizer.normalize(text)
        assert "    " not in result
        assert result.count("\n\n") <= 1

    def test_fix_sentence_breaks(self):
        """测试句号后无空格修复。"""
        normalizer = TextNormalizer()
        text = "We propose a method.Word continues."
        result, warnings = normalizer.normalize(text)
        assert ". Word" in result or ".  W" in result

    def test_remove_arxiv_id_noise(self):
        """测试去除 arXiv ID 噪声行。"""
        normalizer = TextNormalizer()
        text = "arXiv:1706.03762v1\nReal content here\ndoi:10.1000/test"
        result, warnings = normalizer.normalize(text)
        assert "arXiv:1706.03762v1" not in result
        assert "Real content here" in result

    def test_remove_page_number_noise(self):
        """测试去除页码噪声。"""
        normalizer = TextNormalizer()
        text = "1 / 10\nReal content here\nPage 2 of 5"
        result, warnings = normalizer.normalize(text)
        assert "1 / 10" not in result
        assert "Page 2 of 5" not in result
        assert "Real content here" in result

    def test_short_text_warning(self):
        """测试过短文本触发警告。"""
        normalizer = TextNormalizer()
        text = "Short"
        _, warnings = normalizer.normalize(text)
        assert any("过短" in w for w in warnings)


class TestMetadataNormalizer:
    """Metadata Normalizer 测试。"""

    def test_normalize_title_version_suffix(self):
        """测试去掉标题版本后缀。"""
        normalizer = MetadataNormalizer()
        assert normalizer.normalize_title("Attention Is All You Need v1") == "Attention Is All You Need"
        assert normalizer.normalize_title("Test Paper [v2]") == "Test Paper"
        assert normalizer.normalize_title("Methodology (revised)") == "Methodology"

    def test_normalize_title_strip_punctuation(self):
        """测试去掉标题首尾标点。"""
        normalizer = MetadataNormalizer()
        assert normalizer.normalize_title("  Title  ") == "Title"
        assert normalizer.normalize_title("Title...") == "Title"
        assert normalizer.normalize_title("Title . ") == "Title"

    def test_normalize_authors_split(self):
        """测试作者列表拆分。"""
        normalizer = MetadataNormalizer()
        # 字符串输入 → 列表
        result = normalizer.normalize_authors(["John Doe", "Jane Smith"])
        assert result == ["John Doe", "Jane Smith"]
        # 脚注标记去除
        result = normalizer.normalize_authors(["John Doe [1]", "Jane Smith*"])
        assert "[1]" not in result[0]
        assert "*" not in result[1]

    def test_normalize_year(self):
        """测试年份标准化。"""
        normalizer = MetadataNormalizer()
        assert normalizer.normalize_year(2023) == 2023
        assert normalizer.normalize_year("2023") == 2023  # 支持字符串转换
        assert normalizer.normalize_year(1800) is None  # 超出合理范围
        assert normalizer.normalize_year(2050) is None
        assert normalizer.normalize_year(None) is None

    def test_extract_first_author_surname(self):
        """测试提取第一作者 surname。"""
        normalizer = MetadataNormalizer()
        assert normalizer._extract_first_author_surname(["John Doe Smith"]) == "Smith"
        assert normalizer._extract_first_author_surname(["Doe, John"]) == "John"  # 逗号分隔
        assert normalizer._extract_first_author_surname([]) == ""

    def test_normalize_full_pipeline(self):
        """测试完整标准化流水线。"""
        normalizer = MetadataNormalizer()
        result = normalizer.normalize(
            title="  Attention Is All You Need v1  ",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            year=2017,
            venue="NeurIPS",
        )
        assert result.title == "Attention Is All You Need"
        assert len(result.authors) == 2
        assert result.year == 2017
        assert result.venue == "NeurIPS"


class TestNormalizeVenue:
    """Venue 标准化测试。"""

    def test_neurips_aliases(self):
        assert normalize_venue("NeurIPS") == "NeurIPS"
        assert normalize_venue("nips") == "NeurIPS"
        assert normalize_venue("Advances in Neural Information Processing Systems") == "NeurIPS"

    def test_iclr_aliases(self):
        assert normalize_venue("ICLR") == "ICLR"
        assert normalize_venue("iclr") == "ICLR"

    def test_icml_aliases(self):
        assert normalize_venue("ICML") == "ICML"
        assert normalize_venue("international conference on machine learning") == "ICML"

    def test_cvpr_aliases(self):
        assert normalize_venue("CVPR") == "CVPR"
        assert normalize_venue("cvpr 2023") == "CVPR"

    def test_acl_aliases(self):
        assert normalize_venue("ACL") == "ACL"
        assert normalize_venue("Association for Computational Linguistics") == "ACL"

    def test_unknown_venue(self):
        """未知 venue 保持原样。"""
        assert normalize_venue("Some Unknown Venue") == "Some Unknown Venue"
        assert normalize_venue(None) is None

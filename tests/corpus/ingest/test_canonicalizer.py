"""Tests for corpus ingest canonicalizer."""

from __future__ import annotations

import pytest

from src.corpus.ingest.canonicalize import (
    Canonicalizer,
    MergeDecision,
    _strip_arxiv_version,
    _title_similarity,
)


class TestCanonicalizer:
    """Canonicalizer 测试。"""

    def test_build_key_basic(self):
        """测试基本 key 构建。"""
        canon = Canonicalizer()
        key = canon.build_key(
            title="Attention Is All You Need",
            authors=["Ashish Vaswani"],
            year=2017,
            arxiv_id="1706.03762",
        )
        assert key.normalized_title == "attention is all you need"
        assert key.first_author_surname == "vaswani"
        assert key.year == 2017
        assert key.arxiv_id == "1706.03762"
        assert key.doi is None

    def test_build_key_no_authors(self):
        """测试无作者时的 key 构建。"""
        canon = Canonicalizer()
        key = canon.build_key(title="Test Paper", authors=[], year=2020)
        assert key.first_author_surname == ""

    def test_to_hash(self):
        """测试 key hash 生成。"""
        canon = Canonicalizer()
        key = canon.build_key(title="Test", authors=["John Doe"], year=2020)
        hash_val = key.to_hash()
        assert len(hash_val) == 16
        assert hash_val.isalnum()

    def test_confidence_bonus(self):
        """测试置信度加分。"""
        canon = Canonicalizer()
        key_with_all = canon.build_key(
            title="Test",
            authors=["John"],
            year=2020,
            doi="10.1234/test",
            arxiv_id="2001.12345",
            venue="NeurIPS",
        )
        # DOI 0.5 + arXiv ID 0.5 + venue 0.1 = 1.1 → cap at 1.0
        assert key_with_all.confidence_bonus() >= 1.0

        key_doi_only = canon.build_key(
            title="Test", authors=["John"], year=2020, doi="10.1234/test"
        )
        assert key_doi_only.confidence_bonus() == 0.5


class TestMergeDecisions:
    """归并决策测试。"""

    def test_doi_exact_match(self):
        """DOI 完全一致 → 自动归并。"""
        canon = Canonicalizer()
        key1 = canon.build_key(
            title="A", authors=["X"], year=2020, doi="10.1234/abc"
        )
        key2 = canon.build_key(
            title="B", authors=["Y"], year=2021, doi="10.1234/abc"
        )
        decision = canon.decide_merge(key1, key2)
        assert decision.decision == "auto_merge"
        assert decision.confidence >= 0.9

    def test_arxiv_id_match(self):
        """arXiv ID 一致 → 自动归并。"""
        canon = Canonicalizer()
        key1 = canon.build_key(
            title="Test v1", authors=["John"], year=2020, arxiv_id="2001.12345v1"
        )
        key2 = canon.build_key(
            title="Test v2", authors=["John"], year=2021, arxiv_id="2001.12345v2"
        )
        decision = canon.decide_merge(key1, key2)
        assert decision.decision == "auto_merge"
        assert decision.confidence >= 0.9

    def test_high_similarity_same_author_year(self):
        """高相似标题 + 相同作者 + 相同年份 → 自动归并。"""
        canon = Canonicalizer()
        key1 = canon.build_key(
            title="Attention Is All You Need", authors=["Ashish Vaswani"], year=2017
        )
        key2 = canon.build_key(
            title="Attention Is All You Need", authors=["Ashish Vaswani"], year=2017
        )
        decision = canon.decide_merge(key1, key2)
        assert decision.decision == "auto_merge"
        assert decision.confidence >= 0.8

    def test_different_papers(self):
        """差异较大的论文 → 不归并。"""
        canon = Canonicalizer()
        key1 = canon.build_key(
            title="Deep Learning for Vision", authors=["John Doe"], year=2020
        )
        key2 = canon.build_key(
            title="Natural Language Processing", authors=["Jane Smith"], year=2021
        )
        decision = canon.decide_merge(key1, key2)
        assert decision.decision == "keep_separate"


class TestTitleSimilarity:
    """标题相似度测试。"""

    def test_exact_match(self):
        """完全匹配。"""
        assert _title_similarity("test paper", "test paper") == 1.0

    def test_case_insensitive(self):
        """大小写不敏感。"""
        assert _title_similarity("Test Paper", "test paper") == 1.0

    def test_partial_match(self):
        """部分匹配。"""
        sim = _title_similarity(
            "Attention Is All You Need",
            "Attention Is Not All You Need"
        )
        assert 0.3 < sim < 1.0

    def test_no_match(self):
        """完全不匹配。"""
        sim = _title_similarity("Deep Learning", "Natural Language")
        assert sim < 0.2

    def test_empty_title(self):
        """空标题。"""
        assert _title_similarity("", "Test") == 0.0
        assert _title_similarity("Test", "") == 0.0


class TestStripArxivVersion:
    """arXiv 版本号去除测试。"""

    def test_strip_version(self):
        assert _strip_arxiv_version("1706.03762v1") == "1706.03762"
        assert _strip_arxiv_version("1706.03762v5") == "1706.03762"
        assert _strip_arxiv_version("1706.03762") == "1706.03762"
        assert _strip_arxiv_version("2301.05678v99") == "2301.05678"

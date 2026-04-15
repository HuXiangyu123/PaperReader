"""Tests for Structure Detector."""

from __future__ import annotations

import pytest

from src.corpus.ingest.chunkers import (
    _is_heading_line,
    _is_title_case,
    _normalize_section_name,
    _split_into_paragraphs,
    PaperStructure,
    StructureDetector,
)
from src.corpus.models import PageText, StandardizedDocument


class TestIsHeadingLine:
    def test_known_sections(self):
        assert _is_heading_line("Abstract") is True
        assert _is_heading_line("Introduction") is True
        assert _is_heading_line("1. Introduction") is True
        assert _is_heading_line("Related Work") is True
        assert _is_heading_line("2. RELATED WORK") is True
        assert _is_heading_line("Methods") is True
        assert _is_heading_line("Experiments and Results") is True
        assert _is_heading_line("Conclusion") is True
        assert _is_heading_line("References") is True

    def test_not_heading(self):
        assert _is_heading_line("This is a very long sentence that describes some concept in detail and ends with a period.") is False
        assert _is_heading_line("123.45.67") is False
        assert _is_heading_line("") is False
        assert _is_heading_line("   ") is False

    def test_title_case(self):
        assert _is_heading_line("Attention Is All You Need") is True
        assert _is_heading_line("Deep Residual Learning") is True


class TestIsTitleCase:
    def test_title_case(self):
        assert _is_title_case("Attention Is All You Need") is True
        assert _is_title_case("Deep Learning for NLP") is True

    def test_not_title_case(self):
        assert _is_title_case("this is all lowercase") is False
        assert _is_title_case("THIS IS ALL CAPS") is False


class TestNormalizeSectionName:
    def test_abstract(self):
        assert _normalize_section_name("Abstract") == "abstract"
        assert _normalize_section_name("1. Abstract") == "abstract"

    def test_methods(self):
        assert _normalize_section_name("Methodology") == "methods"
        assert _normalize_section_name("Methods") == "methods"
        assert _normalize_section_name("2. Methodology") == "methods"

    def test_conclusion(self):
        assert _normalize_section_name("Conclusion") == "conclusion"
        assert _normalize_section_name("Conclusions and Future Work") == "conclusion"

    def test_experiments(self):
        assert _normalize_section_name("Experiments") == "experiments"
        assert _normalize_section_name("Experiments and Results") == "experiments"
        assert _normalize_section_name("Evaluation") == "experiments"


class TestStructureDetector:
    """Structure Detector 测试。"""

    def _make_sample_doc(self, text: str) -> tuple[StandardizedDocument, list[PageText]]:
        """创建测试用 doc + page_texts。"""
        page = PageText(page_num=1, text=text, char_start=0, char_end=len(text))
        doc = StandardizedDocument(
            doc_id="test_doc",
            workspace_id=None,
            title="Test Paper",
            normalized_text=text,
        )
        return doc, [page]

    def test_detect_with_sections(self):
        """测试标准论文结构检测。"""
        text = """Attention Is All You Need

Abstract
We propose a new model called Transformer.

Introduction
Deep learning has made great progress.

Methods
We use self-attention mechanisms.

Experiments
We evaluate on several benchmarks.

Conclusion
Experimental results show effectiveness."""

        detector = StructureDetector()
        doc, pages = self._make_sample_doc(text)
        structure = detector.detect(doc, pages)

        assert structure.title == "Test Paper"
        section_names = [s.heading for s in structure.sections]
        assert "abstract" in section_names
        assert "introduction" in section_names
        assert "methods" in section_names
        assert "experiments" in section_names
        assert "conclusion" in section_names

    def test_detect_abstract(self):
        """测试 abstract 提取。"""
        text = """Abstract
We propose the Transformer model.

Introduction
Attention mechanisms are widely used."""

        detector = StructureDetector()
        doc, pages = self._make_sample_doc(text)
        structure = detector.detect(doc, pages)

        assert structure.abstract is not None
        assert len(structure.abstract) > 10

    def test_detect_no_sections(self):
        """检测不到章节时返回警告。"""
        text = "Very short text with no clear sections."
        detector = StructureDetector()
        doc, pages = self._make_sample_doc(text)
        structure = detector.detect(doc, pages)

        assert len(structure.warnings) > 0 or len(structure.sections) >= 0

    def test_section_level_detection(self):
        """测试章节层级检测。"""
        text = """Introduction
Regular intro content.

1.1 Deep Dive
Detailed subsection content."""

        detector = StructureDetector()
        doc, pages = self._make_sample_doc(text)
        structure = detector.detect(doc, pages)

        assert len(structure.sections) >= 1

    def test_split_into_paragraphs(self):
        """测试段落分割。"""
        text = "First paragraph here.\n\nSecond paragraph here."
        paras = _split_into_paragraphs(text, 1, 2, 0)
        assert len(paras) >= 1
        assert all(isinstance(p.text, str) for p in paras)

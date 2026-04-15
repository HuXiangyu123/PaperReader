from __future__ import annotations

from src.graph.nodes.classify_paper_type import classify_paper_type
from src.models.paper import NormalizedDocument, PaperMetadata


def _doc(title: str, abstract: str = ""):
    return NormalizedDocument(
        metadata=PaperMetadata(title=title, authors=["A"], abstract=abstract),
        document_text=abstract or title,
        document_sections={},
        source_manifest={},
    )


def test_classify_regular():
    result = classify_paper_type({"normalized_doc": _doc("Attention Is All You Need", "Transformer architecture paper")})
    assert result["paper_type"] == "regular"


def test_classify_survey_by_title():
    result = classify_paper_type({"normalized_doc": _doc("A Survey of LLM Agents", "overview of agent systems")})
    assert result["paper_type"] == "survey"

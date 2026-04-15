from __future__ import annotations

from unittest.mock import patch, MagicMock

from src.graph.nodes.retrieve_evidence import retrieve_evidence
from src.models.paper import PaperMetadata, NormalizedDocument


def _make_doc(title="Test Paper", abstract="A test abstract"):
    meta = PaperMetadata(title=title, authors=["Author"], abstract=abstract)
    return NormalizedDocument(
        metadata=meta,
        document_text="Full text...",
        document_sections={},
        source_manifest={"origin": "test"},
    )


def test_retrieve_no_doc():
    result = retrieve_evidence({})
    assert "errors" in result


def test_retrieve_with_rag():
    doc = _make_doc()
    mock_tool = MagicMock()
    mock_tool.invoke.return_value = (
        "[1] Source: Paper\nContent: chunk1\n---\n"
        "[2] Source: Paper2\nContent: chunk2"
    )
    with patch("src.tools.rag_search.rag_search", mock_tool), \
         patch("src.tools.web_fetch.fetch_webpage_text", MagicMock()):
        result = retrieve_evidence({"normalized_doc": doc})
    assert "evidence" in result
    assert len(result["evidence"].rag_results) >= 1


def test_retrieve_rag_fails_gracefully():
    doc = _make_doc()
    mock_rag = MagicMock()
    mock_rag.invoke.side_effect = Exception("no index")
    mock_web = MagicMock()
    mock_web.invoke.side_effect = Exception("network error")
    with patch("src.tools.rag_search.rag_search", mock_rag), \
         patch("src.tools.web_fetch.fetch_webpage_text", mock_web):
        result = retrieve_evidence({"normalized_doc": doc})
    assert "evidence" in result
    assert len(result["evidence"].rag_results) == 0
    assert "warnings" in result
    w = " ".join(result["warnings"])
    assert "RAG search failed" in w
    assert "web search failed" in w

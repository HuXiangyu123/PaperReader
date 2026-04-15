from src.graph.nodes.normalize_metadata import normalize_metadata


def test_normalize_arxiv():
    state = {
        "source_type": "arxiv",
        "source_manifest": {
            "title": "Attention Is All You Need",
            "authors": ["Vaswani"],
            "abstract": "We propose...",
            "pdf_url": "http://arxiv.org/pdf/1706.03762",
            "published": "2017-06-12",
        },
        "pdf_text": "Full paper text here...",
    }
    result = normalize_metadata(state)
    doc = result["normalized_doc"]
    assert doc.metadata.title == "Attention Is All You Need"
    assert doc.metadata.authors == ["Vaswani"]
    assert doc.metadata.abstract == "We propose..."
    assert doc.metadata.pdf_url == "http://arxiv.org/pdf/1706.03762"
    assert doc.document_text == "Full paper text here..."
    assert doc.document_sections == {}
    assert doc.source_manifest["title"] == "Attention Is All You Need"


def test_normalize_pdf():
    state = {
        "source_type": "pdf",
        "source_manifest": {"origin": "pdf"},
        "pdf_text": "My Paper Title\nIntroduction\nSome content...",
    }
    result = normalize_metadata(state)
    doc = result["normalized_doc"]
    assert doc.metadata.title == "My Paper Title"
    assert doc.metadata.authors == []
    assert doc.document_text.startswith("My Paper Title")


def test_normalize_safe_abort():
    state = {
        "source_type": "arxiv",
        "source_manifest": {},
        "pdf_text": "",
    }
    result = normalize_metadata(state)
    assert result.get("degradation_mode") == "safe_abort"
    assert "errors" in result

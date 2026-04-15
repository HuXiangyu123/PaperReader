from unittest.mock import MagicMock, patch

from src.graph.nodes.ingest_source import ingest_source


def _make_mock_entry():
    entry = MagicMock()
    entry.title = "Attention Is All You Need"
    entry.summary = "The dominant sequence transduction models..."
    entry.published = "2017-06-12T17:57:34Z"
    author = MagicMock()
    author.name = "Ashish Vaswani"
    entry.authors = [author]
    link = MagicMock()
    link.type = "application/pdf"
    link.href = "http://arxiv.org/pdf/1706.03762v7"
    entry.links = [link]
    return entry


def test_ingest_arxiv():
    with patch("src.graph.nodes.ingest_source._parse_arxiv_feed") as mock_fp:
        mock_feed = MagicMock()
        mock_feed.entries = [_make_mock_entry()]
        mock_fp.return_value = mock_feed
        result = ingest_source({"source_type": "arxiv", "arxiv_id": "1706.03762"})
    assert result["source_manifest"]["origin"] == "arxiv"
    assert result["source_manifest"]["title"] == "Attention Is All You Need"
    assert result["source_manifest"]["pdf_url"].endswith("1706.03762v7")


def test_ingest_arxiv_not_found():
    with patch("src.graph.nodes.ingest_source._parse_arxiv_feed") as mock_fp:
        mock_feed = MagicMock()
        mock_feed.entries = []
        mock_fp.return_value = mock_feed
        result = ingest_source({"source_type": "arxiv", "arxiv_id": "9999.99999"})
    assert "errors" in result


def test_ingest_pdf():
    result = ingest_source({"source_type": "pdf", "pdf_text": "some text"})
    assert result["source_manifest"]["origin"] == "pdf"


def test_ingest_missing_arxiv_id():
    result = ingest_source({"source_type": "arxiv"})
    assert "errors" in result


def test_ingest_arxiv_fallback_to_abs_page_when_api_unavailable():
    with patch("src.graph.nodes.ingest_source._parse_arxiv_feed") as mock_fp:
        with patch("src.graph.nodes.ingest_source._fetch_arxiv_abs_fallback") as mock_fb:
            mock_fp.side_effect = RuntimeError("Remote end closed connection without response")
            mock_fb.return_value = {
                "origin": "arxiv",
                "arxiv_id": "1706.03762",
                "title": "Attention Is All You Need",
                "authors": [],
                "abstract": "Transformer paper abstract",
                "published": None,
                "pdf_url": "https://arxiv.org/pdf/1706.03762.pdf",
                "fallback_source": "arxiv_abs_html",
            }
            result = ingest_source({"source_type": "arxiv", "arxiv_id": "1706.03762"})
    assert result["source_manifest"]["origin"] == "arxiv"
    assert result["source_manifest"]["fallback_source"] == "arxiv_abs_html"
    assert result["source_manifest"]["abstract"] == "Transformer paper abstract"

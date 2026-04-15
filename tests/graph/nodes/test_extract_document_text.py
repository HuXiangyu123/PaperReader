from unittest.mock import MagicMock, patch

from src.graph.nodes.extract_document_text import extract_document_text


def test_pdf_passthrough():
    result = extract_document_text({"source_type": "pdf", "pdf_text": "existing text"})
    assert result == {}


def test_pdf_missing_text():
    result = extract_document_text({"source_type": "pdf", "pdf_text": ""})
    assert "errors" in result


def test_arxiv_no_pdf_url():
    result = extract_document_text({"source_type": "arxiv", "source_manifest": {}})
    assert result.get("degradation_mode") == "limited"


def test_arxiv_download_success():
    fake_pdf_bytes = b"%PDF-1.4 fake content"
    mock_resp = MagicMock()
    mock_resp.content = fake_pdf_bytes
    mock_resp.raise_for_status = MagicMock()

    with patch("src.graph.nodes.extract_document_text.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        with patch(
            "src.graph.nodes.extract_document_text.extract_text_from_pdf_bytes"
        ) as mock_extract:
            mock_extract.return_value = "Extracted paper text here"
            result = extract_document_text(
                {
                    "source_type": "arxiv",
                    "source_manifest": {"pdf_url": "http://arxiv.org/pdf/1706.03762"},
                }
            )
    assert result["pdf_text"] == "Extracted paper text here"


def test_arxiv_download_failure():
    with patch("src.graph.nodes.extract_document_text.httpx.Client") as MockClient:
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("connection timeout")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        result = extract_document_text(
            {
                "source_type": "arxiv",
                "source_manifest": {"pdf_url": "http://arxiv.org/pdf/1706.03762"},
            }
        )
    assert result.get("degradation_mode") == "limited"

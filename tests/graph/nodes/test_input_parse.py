from src.graph.nodes.input_parse import input_parse


def test_parse_arxiv_url():
    result = input_parse({"raw_input": "https://arxiv.org/abs/1706.03762"})
    assert result["source_type"] == "arxiv"
    assert result["arxiv_id"] == "1706.03762"


def test_parse_arxiv_id_only():
    result = input_parse({"raw_input": "1706.03762"})
    assert result["source_type"] == "arxiv"
    assert result["arxiv_id"] == "1706.03762"


def test_parse_pdf():
    result = input_parse({"raw_input": "", "pdf_text": "Some extracted PDF text"})
    assert result["source_type"] == "pdf"


def test_parse_invalid():
    result = input_parse({"raw_input": "hello world"})
    assert "errors" in result
    assert len(result["errors"]) > 0
    assert "input_parse" in result["errors"][0]

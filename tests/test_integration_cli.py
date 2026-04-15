from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def _make_arxiv_mocks():
    """Build feedparser + httpx + LLM mocks for the arXiv integration path."""
    mock_entry = MagicMock()
    mock_entry.title = "Attention Is All You Need"
    mock_entry.summary = "The dominant sequence transduction models..."
    mock_entry.published = "2017-06-12"
    author = MagicMock()
    author.name = "Vaswani"
    mock_entry.authors = [author]
    link = MagicMock()
    link.type = "application/pdf"
    link.href = "http://arxiv.org/pdf/1706.03762v7"
    link.title = "pdf"
    mock_entry.links = [link]

    mock_feed = MagicMock()
    mock_feed.entries = [mock_entry]

    return mock_feed


def _make_draft_llm(sections: dict, claims: list | None = None, citations: list | None = None):
    """Build a mock LLM that returns a draft JSON blob."""
    if claims is None:
        claims = [{"id": "c1", "text": "achieves SOTA", "citation_labels": ["[1]"]}]
    if citations is None:
        citations = [{"label": "[1]", "url": "https://arxiv.org/abs/1706.03762", "reason": "original paper"}]

    draft_json = json.dumps({"sections": sections, "claims": claims, "citations": citations})
    mock_resp = MagicMock()
    mock_resp.content = draft_json
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_resp
    return mock_llm


def _base_state(**overrides) -> dict:
    state = {
        "raw_input": "",
        "source_type": "arxiv",
        "arxiv_id": None,
        "pdf_text": None,
        "source_manifest": None,
        "normalized_doc": None,
        "evidence": None,
        "draft_report": None,
        "resolved_report": None,
        "verified_report": None,
        "final_report": None,
        "tokens_used": 0,
        "warnings": [],
        "errors": [],
        "degradation_mode": "normal",
        "node_statuses": {},
    }
    state.update(overrides)
    return state


def test_graph_produces_final_report_for_arxiv():
    """Integration: mock external calls, verify graph runs end-to-end for arXiv."""
    from src.graph.builder import build_report_graph

    mock_feed = _make_arxiv_mocks()
    mock_llm = _make_draft_llm(
        sections={
            "标题": "Attention Is All You Need",
            "核心贡献": "Transformer",
            "方法概述": "Self-attention",
            "关键实验": "BLEU",
            "局限性": "Compute cost",
        },
    )

    with (
        patch("src.graph.nodes.ingest_source.feedparser.parse", return_value=mock_feed),
        patch("src.graph.nodes.extract_document_text.httpx.Client") as MockClient,
        patch(
            "src.graph.nodes.extract_document_text.extract_text_from_pdf_bytes",
            return_value="Full paper text here",
        ),
        patch("src.agent.settings.Settings.from_env", return_value=MagicMock()),
        patch("src.agent.llm.build_deepseek_chat", return_value=mock_llm),
    ):
        mock_resp = MagicMock()
        mock_resp.content = b"%PDF-fake"
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = mock_client

        graph = build_report_graph()
        result = graph.invoke(_base_state(raw_input="1706.03762"))

    assert result["final_report"] is not None
    assert result["final_report"].report_confidence in ("high", "limited", "low")
    assert "Attention" in result["final_report"].sections.get("标题", "")


def test_graph_produces_final_report_for_pdf():
    """Integration: PDF path — pdf_text provided, skips arXiv fetch."""
    from src.graph.builder import build_report_graph

    mock_llm = _make_draft_llm(
        sections={
            "标题": "Some PDF Paper",
            "核心贡献": "Novel approach",
            "方法概述": "Method",
            "关键实验": "Results",
            "局限性": "Limits",
        },
        claims=[{"id": "c1", "text": "improves X", "citation_labels": ["[1]"]}],
        citations=[{"label": "[1]", "url": "https://example.com", "reason": "reference"}],
    )

    with (
        patch("src.agent.settings.Settings.from_env", return_value=MagicMock()),
        patch("src.agent.llm.build_deepseek_chat", return_value=mock_llm),
    ):
        graph = build_report_graph()
        result = graph.invoke(
            _base_state(
                raw_input="",
                source_type="pdf",
                pdf_text="Title of Paper\nIntroduction\nThis paper presents...",
            )
        )

    assert result["final_report"] is not None
    assert result["final_report"].report_confidence in ("high", "limited", "low")


def test_generate_literature_report_uses_graph():
    """Verify that generate_literature_report routes to the graph for non-chat calls."""
    from src.graph.builder import build_report_graph

    mock_llm = _make_draft_llm(
        sections={
            "标题": "Test Paper",
            "核心贡献": "X",
            "方法概述": "Y",
            "关键实验": "Z",
            "局限性": "W",
        },
    )

    with (
        patch("src.agent.settings.Settings.from_env", return_value=MagicMock()),
        patch("src.agent.llm.build_deepseek_chat", return_value=mock_llm),
    ):
        from src.agent.report import generate_literature_report

        result = generate_literature_report(
            raw_text_content="Title of Paper\nIntroduction\nThis paper presents..."
        )

    assert isinstance(result, str)
    assert "Test Paper" in result

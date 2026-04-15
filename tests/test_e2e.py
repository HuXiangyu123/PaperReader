"""End-to-end test: POST /tasks → poll status → verify report."""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.app import app
from src.api.routes.tasks import clear_tasks_store


def _setup_mocks():
    """Return context managers for all external dependencies."""
    mock_entry = MagicMock()
    mock_entry.title = "Attention Is All You Need"
    mock_entry.summary = (
        "The dominant sequence transduction models are based on complex "
        "recurrent or convolutional neural networks."
    )
    mock_entry.published = "2017-06-12T17:57:34Z"
    author = MagicMock()
    author.name = "Ashish Vaswani"
    mock_entry.authors = [author]
    link = MagicMock()
    link.type = "application/pdf"
    link.href = "http://arxiv.org/pdf/1706.03762v7"
    link.title = "pdf"
    mock_entry.links = [link]
    mock_feed = MagicMock()
    mock_feed.entries = [mock_entry]

    draft_json = json.dumps({
        "sections": {
            "标题": "Attention Is All You Need",
            "核心贡献": "Proposes the Transformer architecture based entirely on attention mechanisms.",
            "方法概述": "Self-attention replaces recurrence and convolutions.",
            "关键实验": "Achieves 28.4 BLEU on WMT 2014 EN-DE.",
            "局限性": "High computational cost for very long sequences.",
        },
        "claims": [
            {"id": "c1", "text": "Transformer achieves state-of-the-art BLEU score", "citation_labels": ["[1]"]},
            {"id": "c2", "text": "Self-attention is more parallelizable than recurrence", "citation_labels": ["[1]"]},
        ],
        "citations": [
            {"label": "[1]", "url": "https://arxiv.org/abs/1706.03762", "reason": "Original Transformer paper"},
            {"label": "[2]", "url": "https://github.com/tensorflow/tensor2tensor", "reason": "Reference implementation"},
        ],
    })
    mock_llm_resp = MagicMock()
    mock_llm_resp.content = draft_json
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_llm_resp

    mock_http_resp = MagicMock()
    mock_http_resp.content = b"%PDF-1.4 fake"
    mock_http_resp.raise_for_status = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_client = MagicMock()
    mock_http_client.get.return_value = mock_http_resp
    mock_http_client.head.return_value = mock_http_resp
    mock_http_client.__enter__ = MagicMock(return_value=mock_http_client)
    mock_http_client.__exit__ = MagicMock(return_value=False)

    # Settings and build_deepseek_chat are late-bound imports inside function
    # bodies (draft_report, repair_report, verify_claims), so we patch at the
    # *source* module rather than the individual node modules.
    return {
        "feedparser": patch(
            "src.graph.nodes.ingest_source.feedparser.parse",
            return_value=mock_feed,
        ),
        "httpx_client": patch(
            "src.graph.nodes.extract_document_text.httpx.Client",
            return_value=mock_http_client,
        ),
        "pdf_extract": patch(
            "src.graph.nodes.extract_document_text.extract_text_from_pdf_bytes",
            return_value="Full paper text about Transformer architecture and self-attention mechanisms.",
        ),
        "settings": patch("src.agent.settings.Settings"),
        "llm_builder": patch(
            "src.agent.llm.build_deepseek_chat", return_value=mock_llm,
        ),
        "reachability": patch(
            "src.graph.nodes.resolve_citations.check_url_reachable_sync",
            return_value=True,
        ),
        "fetch_snippet": patch(
            "src.graph.nodes.resolve_citations._fetch_content_snippet",
            return_value="Transformer paper content",
        ),
    }


def test_e2e_arxiv_task():
    """Full flow: create task → poll → get result."""
    clear_tasks_store()
    mocks = _setup_mocks()
    started = [m.start() for m in mocks.values()]

    try:
        with TestClient(app) as client:
            resp = client.post("/tasks", json={"input_type": "arxiv", "input_value": "1706.03762"})
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]
            assert task_id

            final_status = None
            data = None
            for _ in range(60):
                resp = client.get(f"/tasks/{task_id}")
                assert resp.status_code == 200
                data = resp.json()
                if data["status"] in ("completed", "failed"):
                    final_status = data["status"]
                    break
                time.sleep(0.5)

            assert final_status == "completed", (
                f"Task ended with status: {final_status}, error: {data.get('error') if data else 'no data'}"
            )
            assert data["result_markdown"] is not None
            assert len(data["result_markdown"]) > 50
            assert "Attention" in data["result_markdown"]
            assert "引用" in data["result_markdown"] or "[1]" in data["result_markdown"]
    finally:
        for m in mocks.values():
            m.stop()
        clear_tasks_store()


def test_e2e_boundary_invalid_input():
    """Invalid input should result in a failed task or error report."""
    clear_tasks_store()

    try:
        with TestClient(app) as client:
            resp = client.post(
                "/tasks",
                json={"input_type": "arxiv", "input_value": "not_an_arxiv_id"},
            )
            assert resp.status_code == 200
            task_id = resp.json()["task_id"]

            data = None
            for _ in range(30):
                resp = client.get(f"/tasks/{task_id}")
                data = resp.json()
                if data["status"] in ("completed", "failed"):
                    break
                time.sleep(0.5)

            assert data["status"] in ("completed", "failed")
    finally:
        clear_tasks_store()

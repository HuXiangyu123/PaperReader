from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.graph.nodes.report_frame import report_frame
from src.models.paper import EvidenceBundle, NormalizedDocument, PaperMetadata


def _state():
    doc = NormalizedDocument(
        metadata=PaperMetadata(title="Attention", authors=["Vaswani"], abstract="Transformer paper"),
        document_text="Full paper text here",
        document_sections={},
        source_manifest={},
    )
    return {"normalized_doc": doc, "evidence": EvidenceBundle(rag_results=[], web_results=[])}


def test_report_frame_generates_draft_report():
    response = MagicMock()
    response.content = json.dumps({
        "sections": {
            "论文信息": "paper info",
            "I. 摘要与研究动机": "motivation",
            "II. 背景与相关工作": "related work",
            "III. 方法": "method",
            "IV. 实验": "experiments",
            "V. 讨论与未来方向": "discussion",
            "VI. 总结和展望": "summary",
        },
        "claims": [{"id": "c1", "text": "claim", "citation_labels": ["[1]"]}],
        "citations": [{"label": "[1]", "url": "https://example.com", "reason": "source"}],
    })
    with patch("src.agent.settings.Settings.from_env") as mock_env, patch("src.agent.llm.build_chat_llm") as mock_build:
        mock_env.return_value = MagicMock()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = response
        mock_build.return_value = mock_llm
        result = report_frame(_state())

    assert "report_frame" in result
    assert "draft_report" in result
    assert result["draft_report"].sections["III. 方法"] == "method"

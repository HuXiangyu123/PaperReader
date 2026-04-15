from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from src.graph.nodes.survey_intro_outline import survey_intro_outline
from src.models.paper import NormalizedDocument, PaperMetadata


def _state():
    doc = NormalizedDocument(
        metadata=PaperMetadata(title="A Survey of Agents", authors=["A"], abstract="This survey reviews agents."),
        document_text="Survey full text",
        document_sections={},
        source_manifest={},
    )
    return {"normalized_doc": doc}


def test_survey_intro_outline_generates_followup_hints():
    response = MagicMock()
    response.content = json.dumps({
        "sections": {
            "论文信息": "paper info",
            "Intro 翻译": "translated intro",
            "综述大纲": "outline markdown",
            "建议追问": "continue with related work",
        },
        "outline": {"方向一": ["要点1"]},
        "followup_hints": ["继续展开相关工作"],
        "claims": [],
        "citations": [{"label": "[1]", "url": "https://example.com", "reason": "source"}],
    })
    with patch("src.agent.settings.Settings.from_env") as mock_env, patch("src.agent.llm.build_chat_llm") as mock_build:
        mock_env.return_value = MagicMock()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = response
        mock_build.return_value = mock_llm
        result = survey_intro_outline(_state())

    assert result["paper_type"] == "survey"
    assert result["followup_hints"] == ["继续展开相关工作"]
    assert result["draft_report"].sections["Intro 翻译"] == "translated intro"

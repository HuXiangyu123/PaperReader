"""Tests for run_clarify_node graph node."""

from unittest.mock import MagicMock, patch

import pytest

from src.research.graph.nodes.clarify import run_clarify_node


# ---------------------------------------------------------------------------
# run_clarify_node — basic guard checks
# ---------------------------------------------------------------------------

def test_node_requires_research_source_type():
    result = run_clarify_node({"source_type": "arxiv", "raw_input": "调研多模态"})
    assert "errors" in result
    assert "source_type must be 'research'" in result["errors"][0]


def test_node_requires_non_empty_raw_input():
    result = run_clarify_node({"source_type": "research", "raw_input": "   "})
    assert "errors" in result
    assert "raw_input is empty" in result["errors"][0]


def test_node_requires_raw_input_key():
    result = run_clarify_node({"source_type": "research"})
    assert "errors" in result


# ---------------------------------------------------------------------------
# run_clarify_node — normal input
# ---------------------------------------------------------------------------

def test_node_normal_input_writes_brief(monkeypatch):
    """Normal research query should produce brief and done node_status."""
    state = {"source_type": "research", "raw_input": "调研多模态学习方法。"}

    mock_result = MagicMock()
    mock_result.warnings = []
    mock_result.brief.model_dump.return_value = {
        "topic": "多模态学习",
        "goal": "调研",
        "desired_output": "survey_outline",
        "sub_questions": ["有哪些方法？"],
        "time_range": "近三年",
        "domain_scope": "多模态",
        "source_constraints": [],
        "focus_dimensions": ["方法"],
        "ambiguities": [],
        "needs_followup": False,
        "confidence": 0.9,
        "schema_version": "v1",
    }
    mock_result.brief.needs_followup = False
    mock_result.brief.confidence = 0.9

    with patch(
        "src.research.graph.nodes.clarify.run_clarify_agent",
        return_value=mock_result,
    ):
        result = run_clarify_node(state)

    assert "brief" in result
    assert result["current_stage"] == "clarify"
    assert result["node_statuses"]["clarify"]["status"] == "done"


# ---------------------------------------------------------------------------
# run_clarify_node — needs_followup sets warning
# ---------------------------------------------------------------------------

def test_node_needs_followup_adds_warning(monkeypatch):
    """Brief with needs_followup=True should emit a downstream planning warning."""
    state = {"source_type": "research", "raw_input": "帮我看看有什么好方法。"}

    mock_result = MagicMock()
    mock_result.warnings = []
    mock_result.brief.model_dump.return_value = {
        "topic": "未明确",
        "goal": "初步探索",
        "desired_output": "research_brief",
        "sub_questions": ["用户想调研什么领域？"],
        "time_range": "最近",
        "domain_scope": None,
        "source_constraints": [],
        "focus_dimensions": [],
        "ambiguities": [
            {"field": "topic", "reason": "没有说明", "suggested_options": []}
        ],
        "needs_followup": True,
        "confidence": 0.28,
        "schema_version": "v1",
    }
    mock_result.brief.needs_followup = True
    mock_result.brief.confidence = 0.28

    with patch(
        "src.research.graph.nodes.clarify.run_clarify_agent",
        return_value=mock_result,
    ):
        result = run_clarify_node(state)

    assert result["node_statuses"]["clarify"]["status"] == "done"
    assert any("needs_followup=True" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# run_clarify_node — exception handling
# ---------------------------------------------------------------------------

def test_node_exception_returns_failed_status():
    state = {"source_type": "research", "raw_input": "调研多模态。"}

    with patch(
        "src.research.graph.nodes.clarify.run_clarify_agent",
        side_effect=RuntimeError("LLM service unavailable"),
    ):
        result = run_clarify_node(state)

    assert "errors" in result
    assert any("RuntimeError" in e for e in result["errors"])
    assert result["node_statuses"]["clarify"]["status"] == "failed"
    assert result["current_stage"] == "clarify"

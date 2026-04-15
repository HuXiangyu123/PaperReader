"""Tests for ClarifyAgentService."""

from unittest.mock import MagicMock, patch

import pytest

from src.research.agents.clarify_agent import (
    ParseStrategy,
    _try_json_parse,
    run,
)
from src.research.research_brief import ClarifyInput, ResearchBrief


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_brief(
    topic="多模态学习",
    goal="调研多模态方法",
    desired_output="survey_outline",
    sub_questions=None,
    confidence=0.85,
    needs_followup=False,
    **overrides,
) -> dict:
    if sub_questions is None:
        sub_questions = ["多模态有哪些主流方法？"]
    return {
        "topic": topic,
        "goal": goal,
        "desired_output": desired_output,
        "sub_questions": sub_questions,
        "time_range": "近三年",
        "domain_scope": "多模态",
        "source_constraints": [],
        "focus_dimensions": ["方法", "数据集"],
        "ambiguities": [],
        "needs_followup": needs_followup,
        "confidence": confidence,
        "schema_version": "v1",
        **overrides,
    }


def _mock_llm_response(text: str) -> MagicMock:
    """Return a mock LLM response object with .content = text."""
    msg = MagicMock()
    msg.content = text
    return msg


# ---------------------------------------------------------------------------
# _try_json_parse
# ---------------------------------------------------------------------------

def test_try_json_parse_valid():
    raw = '{"topic":"测试","goal":"调研","desired_output":"survey_outline","sub_questions":["问题"],"time_range":null,"domain_scope":null,"source_constraints":[],"focus_dimensions":[],"ambiguities":[],"needs_followup":false,"confidence":0.8,"schema_version":"v1"}'
    brief = _try_json_parse(raw)
    assert brief is not None
    assert brief.topic == "测试"
    assert brief.confidence == 0.8


def test_try_json_parse_with_markdown_code_fence():
    raw = '```json\n{"topic":"测试","goal":"调研","desired_output":"survey_outline","sub_questions":["问题"],"time_range":null,"domain_scope":null,"source_constraints":[],"focus_dimensions":[],"ambiguities":[],"needs_followup":false,"confidence":0.8,"schema_version":"v1"}\n```'
    brief = _try_json_parse(raw)
    assert brief is not None
    assert brief.topic == "测试"


def test_try_json_parse_malformed_returns_none():
    raw = '{"topic": invalid json here}'
    assert _try_json_parse(raw) is None


def test_try_json_parse_extra_fields_ignored():
    raw = '{"topic":"测试","goal":"调研","desired_output":"survey_outline","sub_questions":["问题"],"time_range":null,"domain_scope":null,"source_constraints":[],"focus_dimensions":[],"ambiguities":[],"needs_followup":false,"confidence":0.8,"schema_version":"v1","extra_field":"ignored"}'
    brief = _try_json_parse(raw)
    assert brief is not None


# ---------------------------------------------------------------------------
# run() — normal input
# ---------------------------------------------------------------------------

def test_run_clear_input_returns_valid_brief():
    """Clear query → high-confidence brief, needs_followup=False."""
    input_obj = ClarifyInput(
        raw_query="请调研近三年多模态医学报告生成方向，输出综述大纲。"
    )

    mock_result = _mock_llm_response(
        '{"topic":"多模态医学报告生成","goal":"调研","desired_output":"survey_outline",'
        '"sub_questions":["有哪些方法？"],"time_range":"近三年","domain_scope":"医学影像",'
        '"source_constraints":[],"focus_dimensions":["方法"],"ambiguities":[],'
        '"needs_followup":false,"confidence":0.9,"schema_version":"v1"}'
    )

    def fake_build_llm(settings, max_tokens=8192):
        mock = MagicMock()
        mock.invoke.return_value = mock_result
        return mock

    with patch(
        "src.research.agents.clarify_agent._try_structured_output", lambda *a, **kw: None
    ):
        with patch("src.research.agents.clarify_agent.build_chat_llm", fake_build_llm):
            result = run(input_obj)

    assert result.brief.topic == "多模态医学报告生成"
    assert result.brief.needs_followup is False
    assert result.brief.confidence >= 0.8


# ---------------------------------------------------------------------------
# run() — ambiguous input
# ---------------------------------------------------------------------------

def test_run_underspecified_input_sets_followup():
    """Vague query → low-confidence brief with needs_followup=True."""
    input_obj = ClarifyInput(raw_query="帮我看看最近有什么好方法。")

    mock_result = _mock_llm_response(
        '{"topic":"未明确","goal":"初步探索","desired_output":"research_brief",'
        '"sub_questions":["用户具体想调研哪个领域？"],'
        '"time_range":"最近","domain_scope":null,"source_constraints":[],'
        '"focus_dimensions":[],'
        '"ambiguities":[{"field":"topic","reason":"没有说明具体领域","suggested_options":[]}],'
        '"needs_followup":true,"confidence":0.25,"schema_version":"v1"}'
    )

    def fake_build_llm(settings, max_tokens=8192):
        mock = MagicMock()
        mock.invoke.return_value = mock_result
        return mock

    with patch(
        "src.research.agents.clarify_agent._try_structured_output", lambda *a, **kw: None
    ):
        with patch("src.research.agents.clarify_agent.build_chat_llm", fake_build_llm):
            result = run(input_obj)

    assert result.brief.needs_followup is True
    assert result.brief.confidence < 0.5
    assert len(result.brief.ambiguities) > 0


# ---------------------------------------------------------------------------
# run() — malformed LLM output (repair path)
# ---------------------------------------------------------------------------

def test_run_malformed_json_triggers_repair():
    """Malformed JSON should trigger repair path and still return valid brief."""
    input_obj = ClarifyInput(raw_query="调研多模态学习方法。")

    repair_text = (
        '{"topic":"多模态学习","goal":"调研方法","desired_output":"survey_outline",'
        '"sub_questions":["有哪些方法？"],'
        '"time_range":null,"domain_scope":null,"source_constraints":[],'
        '"focus_dimensions":[],'
        '"ambiguities":[],'
        '"needs_followup":false,"confidence":0.7,"schema_version":"v1"}'
    )

    def fake_build_llm(settings, max_tokens=8192):
        mock = MagicMock()
        # First call: malformed JSON → repair
        # Second call (repair pass): valid JSON
        mock.invoke.side_effect = [
            _mock_llm_response('{"topic": broken json, "confidence": 0.5}'),
            _mock_llm_response(repair_text),
        ]
        return mock

    with patch(
        "src.research.agents.clarify_agent._try_structured_output", lambda *a, **kw: None
    ):
        with patch("src.research.agents.clarify_agent.build_chat_llm", fake_build_llm):
            result = run(input_obj)

    assert result.brief.topic in ("多模态学习", "调研多模态学习方法。")
    assert result.brief.model_dump()["schema_version"] == "v1"


# ---------------------------------------------------------------------------
# run() — all strategies fail → limited brief fallback
# ---------------------------------------------------------------------------

def test_run_all_strategies_fail_returns_limited_brief(monkeypatch):
    """When every parsing strategy fails, run() must return a valid limited brief (never crash)."""
    input_obj = ClarifyInput(raw_query="调研一下。")

    def fake_build_llm(settings, max_tokens=8192):
        mock = MagicMock()
        # Always return something that can't be parsed
        mock.invoke.return_value = _mock_llm_response("completely unparseable garbage")
        return mock

    # Also patch structured output to return None
    with patch(
        "src.research.agents.clarify_agent._try_structured_output", lambda *a, **kw: None
    ):
        with patch("src.research.agents.clarify_agent.build_chat_llm", fake_build_llm):
            result = run(input_obj)

    # Must return a valid brief with needs_followup=True
    assert result.brief.needs_followup is True
    assert result.brief.topic == "调研一下。"
    assert len(result.brief.ambiguities) > 0
    # Must not raise
    assert isinstance(result.brief, ResearchBrief)


def test_run_network_failure_still_preserves_explicit_output_hint():
    input_obj = ClarifyInput(
        raw_query="调研 2023-2026 年 AI agent 在医学影像诊断方向的新论文，输出 survey_outline，重点关注数据集和评测指标。"
    )

    with patch(
        "src.research.agents.clarify_agent._try_structured_output", lambda *a, **kw: None
    ):
        with patch(
            "src.research.agents.clarify_agent._invoke_with_few_shot",
            side_effect=RuntimeError("network down"),
        ):
            result = run(input_obj)

    assert result.brief.desired_output == "survey_outline"
    assert result.brief.time_range == "2023-2026"
    assert all(item.field != "desired_output" for item in result.brief.ambiguities)

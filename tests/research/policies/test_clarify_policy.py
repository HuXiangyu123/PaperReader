"""Tests for clarify_policy helpers."""

import pytest

from src.research.policies.clarify_policy import (
    is_brief_valid,
    should_request_followup,
    to_limited_brief,
)
from src.research.research_brief import AmbiguityItem, ResearchBrief


# ---------------------------------------------------------------------------
# is_brief_valid
# ---------------------------------------------------------------------------

def test_is_brief_valid_full_valid():
    brief = ResearchBrief(
        topic="多模态学习",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=["有什么方法？"],
        confidence=0.85,
    )
    assert is_brief_valid(brief) is True


def test_is_brief_valid_empty_topic():
    brief = ResearchBrief(
        topic="  ",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=["问题"],
        confidence=0.8,
    )
    assert is_brief_valid(brief) is False


def test_is_brief_valid_empty_goal():
    brief = ResearchBrief(
        topic="多模态",
        goal="",
        desired_output="survey_outline",
        sub_questions=["问题"],
        confidence=0.8,
    )
    assert is_brief_valid(brief) is False


def test_is_brief_valid_empty_desired_output():
    brief = ResearchBrief(
        topic="多模态",
        goal="调研",
        desired_output="   ",
        sub_questions=["问题"],
        confidence=0.8,
    )
    assert is_brief_valid(brief) is False


def test_is_brief_valid_empty_sub_questions():
    brief = ResearchBrief(
        topic="多模态",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=[],
        confidence=0.8,
    )
    assert is_brief_valid(brief) is False


def test_is_brief_valid_confidence_out_of_range():
    brief = ResearchBrief(
        topic="多模态",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=["问题"],
        confidence=1.5,
    )
    assert is_brief_valid(brief) is False


# ---------------------------------------------------------------------------
# should_request_followup
# ---------------------------------------------------------------------------

def test_should_request_followup_explicit_true():
    brief = ResearchBrief(
        topic="多模态",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=["问题"],
        needs_followup=True,
        confidence=0.9,
    )
    assert should_request_followup(brief) is True


def test_should_request_followup_low_confidence():
    brief = ResearchBrief(
        topic="多模态",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=["问题"],
        needs_followup=False,
        confidence=0.3,
    )
    assert should_request_followup(brief) is True


def test_should_request_followup_ambiguity_on_topic():
    brief = ResearchBrief(
        topic="未明确",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=["问题"],
        needs_followup=False,
        confidence=0.8,
        ambiguities=[
            AmbiguityItem(
                field="topic",
                reason="没有说明具体领域",
                suggested_options=["多模态", "RAG"],
            )
        ],
    )
    assert should_request_followup(brief) is True


def test_should_request_followup_ambiguity_on_desired_output():
    brief = ResearchBrief(
        topic="多模态",
        goal="调研",
        desired_output="research_brief",
        sub_questions=["问题"],
        needs_followup=False,
        confidence=0.8,
        ambiguities=[
            AmbiguityItem(
                field="desired_output",
                reason="没有说明期望的输出形式",
                suggested_options=["survey_outline", "paper_cards"],
            )
        ],
    )
    assert should_request_followup(brief) is True


def test_should_request_followup_minor_ambiguity_still_ok():
    """Ambiguity on non-core field with high confidence → no followup needed."""
    brief = ResearchBrief(
        topic="多模态",
        goal="调研",
        desired_output="survey_outline",
        sub_questions=["问题"],
        needs_followup=False,
        confidence=0.8,
        ambiguities=[
            AmbiguityItem(
                field="time_range",
                reason="时间范围不明确",
                suggested_options=["近一年", "近三年"],
            )
        ],
    )
    assert should_request_followup(brief) is False


# ---------------------------------------------------------------------------
# to_limited_brief
# ---------------------------------------------------------------------------

def test_to_limited_brief_has_correct_fields():
    brief = to_limited_brief("调研多模态。")
    assert brief.topic == "调研多模态。"
    assert brief.needs_followup is True
    assert 0.0 <= brief.confidence <= 0.3
    assert len(brief.sub_questions) >= 1
    assert len(brief.ambiguities) >= 1
    assert brief.schema_version == "v1"


def test_to_limited_brief_empty_query():
    """Empty query should still produce a valid brief, not crash."""
    brief = to_limited_brief("")
    assert brief.topic == "未提供研究主题"
    assert brief.needs_followup is True
    assert brief.schema_version == "v1"


def test_to_limited_brief_preserves_explicit_desired_output():
    brief = to_limited_brief(
        "调研 2023-2026 年 AI agent 在医学影像诊断方向的新论文，输出 survey_outline，重点关注数据集和评测指标。"
    )
    assert brief.topic == "AI agent 在医学影像诊断方向的新论文"
    assert brief.desired_output == "survey_outline"
    assert brief.time_range == "2023-2026"
    assert brief.domain_scope == "医学影像"
    assert "数据集" in brief.focus_dimensions
    assert all(item.field != "desired_output" for item in brief.ambiguities)

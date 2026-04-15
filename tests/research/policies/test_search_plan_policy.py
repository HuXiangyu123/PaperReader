"""Tests for search_plan_policy helpers."""

from src.research.policies.search_plan_policy import to_fallback_plan


def test_to_fallback_plan_uses_clean_topic_and_preserves_no_followup():
    plan = to_fallback_plan(
        {
            "topic": "调研 2023-2026 年 AI agent 在医学影像诊断方向的新论文，输出 survey_outline，重点关注多模态 agent、工具调用、数据集、评测指标和局限性。",
            "time_range": "2023-2026",
            "domain_scope": "医学影像",
            "focus_dimensions": ["多模态", "工具调用", "数据集"],
            "needs_followup": False,
        }
    )

    assert plan.plan_goal == "围绕 2023-2026 AI agent 在医学影像诊断方向的新论文 制定相关研究检索计划"
    assert all("输出 survey_outline" not in query for query in plan.query_groups[0].queries)
    assert plan.query_groups[0].queries[0] == "AI agent 在医学影像诊断方向的新论文 2023-2026"
    assert plan.followup_needed is False


def test_to_fallback_plan_keeps_followup_for_ambiguous_brief():
    plan = to_fallback_plan(
        {
            "topic": "未提供研究主题",
            "needs_followup": True,
        }
    )

    assert plan.followup_needed is True
    assert len(plan.query_groups[0].queries) >= 1

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.models.config import Phase4Config
from src.research.agents.supervisor import AgentSupervisor


def test_supervisor_normalizes_legacy_aliases():
    supervisor = AgentSupervisor(config=Phase4Config())

    assert supervisor.normalize_node_name("plan_search") == "search_plan"
    assert supervisor.normalize_node_name("search_corpus") == "search"
    assert supervisor.normalize_node_name("extract_cards") == "extract"
    assert supervisor.normalize_node_name("synthesize") == "draft"
    assert supervisor.normalize_node_name("revise") == "review"


@pytest.mark.asyncio
async def test_collaborate_resumes_from_missing_stage():
    supervisor = AgentSupervisor(config=Phase4Config())
    calls: list[str] = []

    async def fake_run_node(node_name: str, state: dict, inputs: dict | None = None) -> dict:
        calls.append(node_name)
        if node_name == "search":
            return {
                "rag_result": {"paper_candidates": [{"title": "p1"}]},
                "current_stage": "search",
                "_backend_mode": "v2",
                "_agent_paradigm": "tag",
            }
        if node_name == "extract":
            return {
                "paper_cards": [{"title": "p1"}],
                "current_stage": "extract",
                "_backend_mode": "legacy",
                "_agent_paradigm": "legacy",
            }
        if node_name == "draft":
            return {
                "draft_report": {"sections": {"introduction": "ok"}},
                "current_stage": "draft",
                "_backend_mode": "v2",
                "_agent_paradigm": "reasoning_via_artifacts",
            }
        if node_name == "review":
            return {
                "review_feedback": {"passed": True},
                "review_passed": True,
                "current_stage": "review",
                "_backend_mode": "v2",
                "_agent_paradigm": "reflexion",
            }
        if node_name == "persist_artifacts":
            return {
                "artifact_count": 4,
                "current_stage": "persist_artifacts",
                "_backend_mode": "legacy",
                "_agent_paradigm": "legacy",
            }
        raise AssertionError(f"unexpected node {node_name}")

    supervisor.run_node = AsyncMock(side_effect=fake_run_node)

    state = {
        "workspace_id": "ws1",
        "task_id": "t1",
        "brief": {"topic": "RAG", "needs_followup": False},
        "search_plan": {"plan_goal": "search", "query_groups": [{"group_id": "g1", "queries": ["rag"]}]},
    }

    result = await supervisor.collaborate(state)

    assert calls == ["search", "extract", "draft", "review", "persist_artifacts"]
    assert result["trace_refs"] == calls
    assert result["collaboration_trace"][0]["node"] == "search"
    assert result["collaboration_trace"][1]["node"] == "extract"
    assert "Supervisor resumed from search" in result["summary"]


@pytest.mark.asyncio
async def test_replan_prunes_downstream_state_before_resuming():
    supervisor = AgentSupervisor(config=Phase4Config())
    captured_state: dict | None = None

    async def fake_collaborate(state: dict, **kwargs) -> dict:
        nonlocal captured_state
        captured_state = dict(state)
        return {"summary": "ok", "trace_refs": ["search_plan"], "collaboration_trace": []}

    supervisor.collaborate = AsyncMock(side_effect=fake_collaborate)

    await supervisor.replan(
        {
            "workspace_id": "ws1",
            "task_id": "t1",
            "brief": {"topic": "RAG"},
            "search_plan": {"plan_goal": "old"},
            "rag_result": {"paper_candidates": [{"title": "p1"}]},
            "paper_cards": [{"title": "p1"}],
            "draft_report": {"sections": {"intro": "x"}},
            "review_feedback": {"passed": False},
        },
        trigger_reason="coverage gap",
        target_stage="search_plan",
    )

    assert captured_state is not None
    assert captured_state["brief"] == {"topic": "RAG"}
    assert "search_plan" not in captured_state
    assert "rag_result" not in captured_state
    assert "paper_cards" not in captured_state

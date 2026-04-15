"""Tests for run_search_plan_node."""

from src.research.graph.nodes.search_plan import run_search_plan_node


def test_search_plan_node_requires_brief():
    result = run_search_plan_node({})
    assert result["search_plan"] is None
    assert result["current_stage"] == "search_plan_failed"


def test_search_plan_node_uses_heuristic_fast_path_for_clear_brief():
    result = run_search_plan_node(
        {
            "use_heuristic": True,
            "brief": {
                "topic": "调研RAG",
                "goal": "为后续综述写作和方法梳理做前期调研",
                "desired_output": "survey_outline",
                "sub_questions": ["RAG近年的代表性方法有哪些？"],
                "time_range": None,
                "domain_scope": None,
                "source_constraints": [],
                "focus_dimensions": [],
                "ambiguities": [],
                "needs_followup": False,
                "confidence": 0.68,
                "schema_version": "v1",
            }
        }
    )

    assert result["current_stage"] == "search_plan"
    assert result["search_plan"] is not None
    first_group_queries = result["search_plan"]["query_groups"][0]["queries"]
    assert any("RAG" in query for query in first_group_queries)
    assert any("fast path" in warning.lower() for warning in result["search_plan_warnings"])

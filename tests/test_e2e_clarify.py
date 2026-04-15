"""End-to-end tests for the research ClarifyAgent workflow.

Tests:
  1. /tasks POST with source_type=research → task accepted
  2. /tasks/{id} GET → task record fields
  3. Graph node produces brief / current_stage / node_statuses
  4. source_type != "research" still works (paper-ingestion path unchanged)
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_clarify_result(warnings=None, needs_followup=False, confidence=0.85):
    """Return a mock ClarifyResult that the clarify agent service returns."""
    from src.research.research_brief import AmbiguityItem, ClarifyResult, ResearchBrief

    return ClarifyResult(
        brief=ResearchBrief(
            topic="多模态学习",
            goal="调研多模态方法",
            desired_output="survey_outline",
            sub_questions=["有哪些多模态方法？"],
            time_range="近三年",
            domain_scope="多模态",
            source_constraints=[],
            focus_dimensions=["方法", "数据集"],
            ambiguities=[],
            needs_followup=needs_followup,
            confidence=confidence,
            schema_version="v1",
        ),
        warnings=warnings or [],
        raw_model_output=None,
    )


# ---------------------------------------------------------------------------
# POST /tasks — source_type=research
# ---------------------------------------------------------------------------

def test_create_research_task_returns_202():
    """POST with source_type=research should return task_id + pending status."""
    with patch("src.api.routes.tasks._run_graph") as mock_run:
        response = client.post(
            "/tasks",
            json={
                "input_type": "research",
                "input_value": "调研多模态学习方法",
                "report_mode": "draft",
                "source_type": "research",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "pending"


def test_create_research_task_source_type_defaults_to_arxiv():
    """source_type defaults to 'arxiv' for backward compatibility."""
    with patch("src.api.routes.tasks._run_graph") as mock_run:
        response = client.post(
            "/tasks",
            json={"input_type": "arxiv", "input_value": "1706.03762"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data


# ---------------------------------------------------------------------------
# GET /tasks/{id} — research task fields
# ---------------------------------------------------------------------------

def test_get_research_task_returns_brief_in_result():
    """A completed research task should expose structured brief/search_plan fields."""
    from src.api.routes.tasks import clear_tasks_store

    clear_tasks_store()

    with patch("src.api.routes.tasks._run_graph") as mock_run:
        create_resp = client.post(
            "/tasks",
            json={
                "input_type": "research",
                "input_value": "调研多模态学习方法",
                "source_type": "research",
            },
        )
    task_id = create_resp.json()["task_id"]

    # Simulate a completed task with a brief
    from src.api.routes.tasks import get_tasks_store
    from src.models.task import TaskStatus

    store = get_tasks_store()
    task = store[task_id]
    task.status = TaskStatus.COMPLETED
    task.brief = {"topic": "多模态学习", "goal": "调研", "desired_output": "survey_outline"}
    task.search_plan = {
        "plan_goal": "调研多模态学习方法",
        "query_groups": [{"group_id": "g1", "queries": ["multimodal learning survey"]}],
    }
    task.current_stage = "search_plan"
    task.result_markdown = '{"brief":{"topic":"多模态学习","goal":"调研","desired_output":"survey_outline"}}'
    task.report_context_snapshot = task.result_markdown

    get_resp = client.get(f"/tasks/{task_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["source_type"] == "research"
    assert "result_markdown" in data
    assert data["brief"]["topic"] == "多模态学习"
    assert data["search_plan"]["plan_goal"] == "调研多模态学习方法"
    assert data["current_stage"] == "search_plan"


# ---------------------------------------------------------------------------
# SSE /events stream
# ---------------------------------------------------------------------------

def test_get_research_task_events_requires_task_id():
    """GET /tasks/{id}/events returns 404 for unknown task."""
    response = client.get("/tasks/nonexistent-id/events")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Graph node produces correct state patch
# ---------------------------------------------------------------------------

def test_clarify_node_writes_brief_and_current_stage():
    """Direct call to run_clarify_node should produce brief + current_stage."""
    from src.research.graph.nodes.clarify import run_clarify_node
    from src.research.research_brief import ClarifyResult, ResearchBrief

    mock_result = ClarifyResult(
        brief=ResearchBrief(
            topic="多模态学习",
            goal="调研",
            desired_output="survey_outline",
            sub_questions=["方法有哪些？"],
            confidence=0.9,
            schema_version="v1",
        ),
        warnings=[],
        raw_model_output=None,
    )

    with patch(
        "src.research.graph.nodes.clarify.run_clarify_agent",
        return_value=mock_result,
    ):
        state = {"source_type": "research", "raw_input": "调研多模态"}
        output = run_clarify_node(state)

    assert "brief" in output
    assert output["current_stage"] == "clarify"
    assert output["node_statuses"]["clarify"]["status"] == "done"
    assert output["node_statuses"]["clarify"]["error"] is None


def test_clarify_node_rejects_non_research_source_type():
    """Node should reject non-research source_type with an error."""
    from src.research.graph.nodes.clarify import run_clarify_node

    result = run_clarify_node({"source_type": "arxiv", "raw_input": "1706.03762"})
    assert "errors" in result


def test_clarify_node_rejects_empty_raw_input():
    """Node should reject empty raw_input."""
    from src.research.graph.nodes.clarify import run_clarify_node

    result = run_clarify_node({"source_type": "research", "raw_input": ""})
    assert "errors" in result


def test_clarify_node_exception_propagates():
    """LLM exception should produce failed node_status."""
    from src.research.graph.nodes.clarify import run_clarify_node

    with patch(
        "src.research.graph.nodes.clarify.run_clarify_agent",
        side_effect=RuntimeError("LLM unreachable"),
    ):
        result = run_clarify_node({"source_type": "research", "raw_input": "调研多模态"})
    assert "errors" in result
    assert "failed" == result["node_statuses"]["clarify"]["status"]


# ---------------------------------------------------------------------------
# Research graph builder
# ---------------------------------------------------------------------------

def test_build_research_graph_compiles():
    """build_research_graph() should preserve brief/search_plan/current_stage."""
    from src.research.graph.builder import build_research_graph

    with patch(
        "src.research.graph.builder.run_clarify_node",
        return_value={
            "brief": {
                "topic": "test",
                "goal": "test",
                "desired_output": "survey_outline",
                "sub_questions": ["q1"],
                "needs_followup": False,
                "confidence": 0.9,
                "schema_version": "v1",
            },
            "current_stage": "clarify",
            "node_statuses": {
                "clarify": {"status": "done", "error": None},
            },
        },
    ), patch(
        "src.research.graph.builder.run_search_plan_node",
        return_value={
            "search_plan": {
                "plan_goal": "test",
                "query_groups": [{"group_id": "g1", "queries": ["test query"]}],
            },
            "search_plan_warnings": [],
            "current_stage": "search_plan",
        },
    ):
        graph = build_research_graph()
        output = graph.invoke({"source_type": "research", "raw_input": "test"})

    assert "node_statuses" in output
    assert "clarify" in output["node_statuses"]
    assert output["node_statuses"]["clarify"]["status"] == "done"
    assert output["node_statuses"]["clarify"]["error"] is None
    assert output["brief"]["topic"] == "test"
    assert output["search_plan"]["plan_goal"] == "test"
    assert output["current_stage"] == "search_plan"

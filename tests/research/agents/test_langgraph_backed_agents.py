from __future__ import annotations

from src.models.research import SearchPlan
from src.research.agents.analyst_agent import AnalystAgent
from src.research.agents.clarify_agent import build_clarify_agent_graph, run as run_clarify_agent
from src.research.agents.planner_agent import PlannerAgent
from src.research.agents.retriever_agent import RetrieverAgent
from src.research.agents.reviewer_agent import ReviewerAgent, SelfReflection
from src.research.research_brief import ClarifyInput, ResearchBrief


def _make_brief(**overrides) -> ResearchBrief:
    data = {
        "topic": "RAG",
        "goal": "survey_drafting",
        "desired_output": "research_brief",
        "sub_questions": ["What retrieval strategies work best?"],
        "needs_followup": False,
        "confidence": 0.9,
    }
    data.update(overrides)
    return ResearchBrief.model_validate(data)


def test_clarify_agent_builds_langgraph_strategy_graph(monkeypatch):
    graph = build_clarify_agent_graph().get_graph()
    assert {
        "prepare",
        "fast_path",
        "structured_output",
        "json_parse",
        "repair",
        "limited",
        "post_validate",
    }.issubset(graph.nodes)

    monkeypatch.setattr(
        "src.research.agents.clarify_agent._fast_path_brief",
        lambda input_obj: _make_brief(topic=input_obj.raw_query.upper()),
    )

    result = run_clarify_agent(ClarifyInput(raw_query="rag"))

    assert result.brief.topic == "RAG"
    assert result.raw_model_output is None


def test_planner_agent_run_executes_langgraph_nodes_in_order(monkeypatch):
    agent = PlannerAgent()
    graph = agent.build_graph().get_graph()
    assert {"plan", "execute", "validate"}.issubset(graph.nodes)

    calls: list[str] = []
    plan = SearchPlan.model_validate(
        {
            "plan_goal": "Collect recent RAG papers",
            "query_groups": [
                {
                    "group_id": "g1",
                    "queries": ["retrieval augmented generation"],
                    "intent": "exploration",
                    "priority": 1,
                    "expected_hits": 5,
                }
            ],
        }
    )

    def fake_plan_phase(brief: dict) -> dict:
        calls.append("plan")
        return {"plan": plan, "phases": ["phase-1"]}

    def fake_execute_phase(phases: list[str]) -> dict:
        calls.append("execute")
        assert phases == ["phase-1"]
        return {"candidates": [{"title": "Paper 1"}], "execution_log": [{"phase": "phase-1"}]}

    def fake_validate_phase(brief: dict, plan_obj: SearchPlan, execution_results: dict) -> dict:
        calls.append("validate")
        assert plan_obj.plan_goal == "Collect recent RAG papers"
        return {
            "validation": {"status": "complete"},
            "candidates": execution_results["candidates"],
            "execution_log": execution_results["execution_log"],
        }

    monkeypatch.setattr(agent, "plan_phase", fake_plan_phase)
    monkeypatch.setattr(agent, "execute_phase", fake_execute_phase)
    monkeypatch.setattr(agent, "validate_phase", fake_validate_phase)

    result = agent.run({"topic": "RAG"})

    assert calls == ["plan", "execute", "validate"]
    assert result["search_plan"]["plan_goal"] == "Collect recent RAG papers"
    assert result["validation"]["status"] == "complete"


def test_retriever_agent_run_builds_rag_result_with_langgraph(monkeypatch):
    agent = RetrieverAgent(workspace_id="ws-1")
    graph = agent.build_graph().get_graph()
    assert {
        "augmented_query_gen",
        "parallel_retrieval",
        "context_assembly",
        "finalize_rag_result",
    }.issubset(graph.nodes)

    monkeypatch.setattr(
        agent,
        "_augmented_query_gen",
        lambda brief: {"queries": [{"query": "rag", "sources": ["arxiv"], "expected_hits": 5}]},
    )
    monkeypatch.setattr(
        agent,
        "_parallel_retrieval",
        lambda queries: {
            "raw_results": [
                {
                    "query": "rag",
                    "hits": [{"title": "RAG Paper", "url": "https://example.com/p1", "content": "abstract"}],
                }
            ]
        },
    )
    monkeypatch.setattr(
        agent,
        "_context_assembly",
        lambda brief, raw_results: [
            {
                "rank": 1,
                "title": "RAG Paper",
                "url": "https://example.com/p1",
                "abstract": "abstract",
                "source": "arxiv",
            }
        ],
    )
    monkeypatch.setattr(
        "src.research.graph.nodes.search._ingest_paper_candidates",
        lambda candidates, workspace_id=None: None,
    )

    result = agent.run({"topic": "RAG"}, {"plan_goal": "Collect RAG"})

    assert result["queries_generated"] == 1
    assert result["rag_result"]["query"] == "Collect RAG"
    assert result["rag_result"]["paper_candidates"][0]["title"] == "RAG Paper"


def test_analyst_agent_run_emits_draft_report_and_markdown(monkeypatch):
    agent = AnalystAgent()
    graph = agent.build_graph().get_graph()
    assert {
        "seed_reasoning_state",
        "build_structured_cards",
        "build_comparison_matrix",
        "build_outline",
        "build_report_draft",
        "verify_and_finalize",
    }.issubset(graph.nodes)

    monkeypatch.setattr(
        agent,
        "_build_structured_cards",
        lambda paper_cards: {
            "cards": [{"title": "Paper 1", "methods": ["Dense retrieval"], "datasets": ["MS MARCO"]}],
            "confidence": 0.7,
        },
    )
    monkeypatch.setattr(
        agent,
        "_build_comparison_matrix",
        lambda artifacts: {"matrix": {"rows": [{"paper": "Paper 1", "methods": "Dense retrieval"}]}, "confidence": 0.8},
    )
    monkeypatch.setattr(
        agent,
        "_build_outline",
        lambda state: {"outline": {"introduction": ["Background"], "methods": ["Dense retrieval"]}, "confidence": 0.75},
    )
    monkeypatch.setattr(
        agent,
        "_build_report_draft",
        lambda state: {
            "draft": {
                "sections": {
                    "title": "RAG Survey",
                    "abstract": "Summary",
                    "introduction": "Intro",
                    "methods": "Methods",
                    "conclusion": "Done",
                },
                "claims": [],
                "citations": [],
            },
            "confidence": 0.85,
        },
    )
    monkeypatch.setattr(agent, "_store_artifacts_memory", lambda state: None)

    result = agent.run({"topic": "RAG"}, [{"title": "Paper 1"}])

    assert result["draft_report"].sections["title"] == "RAG Survey"
    assert result["draft_markdown"].startswith("# RAG Survey")
    assert result["overall_confidence"] > 0


def test_reviewer_agent_langgraph_loops_until_review_passes(monkeypatch):
    agent = ReviewerAgent()
    graph = agent.build_graph().get_graph()
    assert {
        "retrieve_memory",
        "actor_review",
        "evaluate",
        "self_reflect",
        "finalize",
    }.issubset(graph.nodes)

    attempts: list[int] = []

    monkeypatch.setattr(agent, "_retrieve_reflections", lambda brief, draft_report: [])

    def fake_actor_review(**kwargs):
        attempt = kwargs["attempt"]
        attempts.append(attempt)
        return {"confidence": 0.3 if attempt == 1 else 0.9}

    def fake_evaluate(actor_result: dict, attempt: int) -> dict:
        return {
            "passed": attempt == 2,
            "confidence": actor_result["confidence"],
            "reason": "retry" if attempt == 1 else "ok",
            "task_type": "review_confidence",
            "issues": ["low confidence"] if attempt == 1 else [],
        }

    monkeypatch.setattr(agent, "_actor_review", fake_actor_review)
    monkeypatch.setattr(agent, "_evaluate", fake_evaluate)
    monkeypatch.setattr(
        agent,
        "_self_reflect",
        lambda **kwargs: SelfReflection(
            reflection_id="refl_1",
            task_type="review_confidence",
            failure_context="low confidence",
            root_cause="insufficient coverage",
            lessons=["improve retrieval"],
            improved_strategy="retrieve more evidence",
            confidence_gain=0.1,
            created_at=0.0,
        ),
    )
    monkeypatch.setattr(agent, "_store_reflection", lambda reflection: None)

    result = agent.run({"topic": "RAG"}, [{"title": "Paper 1"}], {"sections": {"introduction": "Intro"}})

    assert attempts == [1, 2]
    assert result["review_passed"] is True
    assert result["total_attempts"] == 2

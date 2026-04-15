"""Research workflow StateGraph builder — Phase 1: Clarify + SearchPlanAgent.

Future nodes (stubbed or pending):
  - search       : execute search (PaperCardExtractor)
  - report       : draft report
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.graph.callbacks import NodeEventEmitter
from src.graph.instrumentation import instrument_node
from src.research.graph.nodes.clarify import run_clarify_node
from src.research.graph.nodes.search_plan import run_search_plan_node


def _route_after_clarify(state: dict) -> str:
    """After clarify: route to search_plan or end (if followup required)."""
    brief = state.get("brief")
    if not brief:
        return END
    needs_followup = brief.get("needs_followup", False)
    if needs_followup:
        # Phase 1: 暂停等待人工澄清，不进入搜索
        return END
    return "search_plan"


def _route_after_search_plan(state: dict) -> str:
    """After search_plan: always end in Phase 1."""
    return END


def build_research_graph(event_emitter: NodeEventEmitter | None = None) -> StateGraph:
    """Build the Phase-1 research workflow graph.

    Nodes:
      clarify     → SearchPlanAgent (ResearchBrief 生成)
      search_plan → 搜索计划生成

    Entry: clarify
    Exit:  END
    """
    from src.graph.state import AgentState

    g = StateGraph(AgentState)

    g.add_node("clarify", instrument_node("clarify", run_clarify_node, event_emitter))
    g.add_node("search_plan", instrument_node("search_plan", run_search_plan_node, event_emitter))

    g.set_entry_point("clarify")

    g.add_conditional_edges("clarify", _route_after_clarify, {
        "search_plan": "search_plan",
        END: END,
    })

    g.add_conditional_edges("search_plan", _route_after_search_plan, {
        END: END,
    })

    return g.compile()

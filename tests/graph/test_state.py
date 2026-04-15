from src.graph.state import AgentState, NodeStatus


def test_node_status_defaults():
    ns = NodeStatus(node="input_parse", status="pending")
    assert ns.tokens_delta == 0
    assert ns.warnings == []
    assert ns.repair_triggered is False


def test_node_status_full():
    ns = NodeStatus(
        node="verify_claims",
        status="done",
        started_at="2026-03-29T10:00:00Z",
        ended_at="2026-03-29T10:00:05Z",
        duration_ms=5000,
        warnings=["slow LLM response"],
        tokens_delta=1234,
    )
    assert ns.duration_ms == 5000
    assert len(ns.warnings) == 1


def test_agent_state_is_typed_dict():
    import typing

    hints = typing.get_type_hints(AgentState, include_extras=True)
    assert "raw_input" in hints
    assert "degradation_mode" in hints
    assert "node_statuses" in hints
    assert "tokens_used" in hints
    assert "warnings" in hints
    assert "errors" in hints


def test_agent_state_annotations():
    """tokens_used, warnings, errors should have Annotated metadata for LangGraph reducers."""
    import typing

    hints = typing.get_type_hints(AgentState, include_extras=True)
    # tokens_used should be Annotated[int, operator.add]
    tokens_hint = hints["tokens_used"]
    assert hasattr(tokens_hint, "__metadata__")
    # errors should be Annotated[list[str], operator.add]
    errors_hint = hints["errors"]
    assert hasattr(errors_hint, "__metadata__")

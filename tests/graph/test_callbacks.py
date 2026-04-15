from src.graph.callbacks import NodeEventEmitter


def test_emitter_no_queue():
    emitter = NodeEventEmitter()
    emitter.on_node_start("input_parse")
    emitter.on_node_end("input_parse", tokens_delta=100, duration_ms=12, status="done")
    assert len(emitter.events) == 2
    assert emitter.events[0]["type"] == "node_start"
    assert emitter.events[1]["tokens_delta"] == 100
    assert emitter.events[1]["duration_ms"] == 12
    assert emitter.events[1]["status"] == "done"


def test_emitter_trace_json():
    emitter = NodeEventEmitter()
    emitter.on_node_start("draft_report")
    trace = emitter.to_trace_json()
    assert "draft_report" in trace


def test_emitter_thinking_and_failed_node_end():
    emitter = NodeEventEmitter()
    emitter.on_thinking("clarify", "Calling structured output.")
    emitter.on_node_end("clarify", status="failed", error="boom")
    assert emitter.events[0]["type"] == "thinking"
    assert emitter.events[1]["status"] == "failed"
    assert emitter.events[1]["error"] == "boom"

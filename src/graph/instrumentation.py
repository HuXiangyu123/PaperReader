from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.graph.callbacks import NodeEventEmitter


def _extract_node_event_payload(node_name: str, output: Any) -> tuple[str, list[str], int, str | None]:
    if not isinstance(output, dict):
        return "done", [], 0, None

    warnings = list(output.get("warnings", []) or output.get("search_plan_warnings", []) or [])
    node_status = (output.get("node_statuses") or {}).get(node_name, {}) if isinstance(output.get("node_statuses"), dict) else {}
    status = node_status.get("status", "done")
    tokens_delta = int(node_status.get("tokens_delta", 0) or 0)
    error = node_status.get("error")
    return status, warnings, tokens_delta, error


def instrument_node(
    node_name: str,
    fn: Callable[[dict], dict],
    emitter: NodeEventEmitter | None = None,
) -> Callable[[dict], dict]:
    def wrapped(state: dict) -> dict:
        started = time.monotonic()
        local_state = dict(state)
        local_state["_event_emitter"] = emitter

        if emitter:
            emitter.on_node_start(node_name)

        try:
            output = fn(local_state)
        except Exception as exc:  # noqa: BLE001
            if emitter:
                emitter.on_node_end(
                    node_name,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    status="failed",
                    error=str(exc),
                )
            raise

        status, warnings, tokens_delta, error = _extract_node_event_payload(node_name, output)
        reasoning = output.get("_reasoning_content") if isinstance(output, dict) else None

        if emitter and reasoning:
            emitter.on_thinking(node_name, reasoning)

        if emitter:
            emitter.on_node_end(
                node_name,
                tokens_delta=tokens_delta,
                warnings=warnings,
                duration_ms=int((time.monotonic() - started) * 1000),
                status=status,
                error=error,
            )

        return output

    return wrapped

"""Graph node: run ClarifyAgent to produce a ResearchBrief from raw user input."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from src.agent.llm import build_chat_llm
from src.agent.settings import Settings
from src.research.agents.clarify_agent import run as run_clarify_agent
from src.research.research_brief import ClarifyInput, ClarifyResult

# ── max_tokens for clarify pass (context is short) ──────────────────────────
_MAX_TOKENS = 4096


def run_clarify_node(state: dict) -> dict:
    """Clarify a raw research request into a structured ResearchBrief.

    Input state fields consumed:
        raw_input : str
            The raw user query. May come from a research-mode task.
        source_type : str
            Must be "research" for this node to run; otherwise returns no-op.

    Output state patch:
        brief          : ResearchBrief as dict (compatible with ResearchBrief.model_validate)
        current_stage  : "clarify"
        warnings       : list[str]  (accumulated via Annotated)
        errors         : list[str]  (accumulated via Annotated)

    This node does NOT run for paper-ingestion mode tasks.
    """
    # Guard: only activate for research-mode tasks
    source_type = state.get("source_type", "")
    if source_type != "research":
        return {"errors": ["run_clarify_node: source_type must be 'research' for clarify"]}

    raw_query = state.get("raw_input", "")
    if not raw_query or not raw_query.strip():
        return {
            "errors": ["run_clarify_node: raw_input is empty"],
            "current_stage": "clarify",
        }

    started_at = datetime.now(UTC).isoformat()
    t0 = time.monotonic()
    emitter = state.get("_event_emitter")

    def emit_progress(message: str) -> None:
        if emitter:
            emitter.on_thinking("clarify", message)

    try:
        inp = ClarifyInput(raw_query=raw_query.strip())
        result: ClarifyResult = run_clarify_agent(inp, emit_progress=emit_progress)

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # Token estimate: ~4 chars/token
        tokens_estimate = len(raw_query) // 4 + 1200
        warnings = list(result.warnings)
        if result.brief.needs_followup:
            warnings.append(
                f"ClarifyAgent flagged needs_followup=True (confidence={result.brief.confidence:.2f}). "
                "Downstream planning should wait for human clarification."
            )

        return {
            "brief": result.brief.model_dump(mode="json"),
            "current_stage": "clarify",
            "warnings": warnings,
            "node_statuses": {
                "clarify": {
                    "node": "clarify",
                    "status": "done",
                    "started_at": started_at,
                    "ended_at": datetime.now(UTC).isoformat(),
                    "duration_ms": elapsed_ms,
                    "warnings": warnings,
                    "error": None,
                    "tokens_delta": tokens_estimate,
                    "repair_triggered": any("repair" in w.lower() for w in warnings),
                }
            },
        }

    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        err_msg = f"run_clarify_node: {type(exc).__name__}: {exc}"
        return {
            "errors": [err_msg],
            "current_stage": "clarify",
            "node_statuses": {
                "clarify": {
                    "node": "clarify",
                    "status": "failed",
                    "started_at": started_at,
                    "ended_at": datetime.now(UTC).isoformat(),
                    "duration_ms": elapsed_ms,
                    "warnings": [],
                    "error": err_msg,
                    "tokens_delta": 0,
                    "repair_triggered": False,
                }
            },
        }

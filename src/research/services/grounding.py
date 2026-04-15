"""Grounding service helpers for the research workflow."""

from __future__ import annotations

import logging
from typing import Any

from src.graph.nodes.format_output import format_output
from src.graph.nodes.resolve_citations import resolve_citations
from src.graph.nodes.verify_claims import verify_claims
from src.models.report import DraftReport

logger = logging.getLogger(__name__)


def ground_draft_report(
    draft_report: DraftReport | None,
    paper_cards: list[Any] | None = None,
    *,
    report_mode: str = "draft",
    degradation_mode: str = "normal",
) -> dict[str, Any]:
    """
    Run the citation-resolution / claim-verification pipeline on a draft.

    Pipeline:
        resolve_citations → verify_claims → format_output

    Each node reads from and writes to the shared state dict.
    The final result includes 'final_report' and 'draft_markdown'.
    """
    if draft_report is None:
        return {}

    state: dict[str, Any] = {
        "draft_report": draft_report,
        "paper_cards": paper_cards or [],
        "report_mode": report_mode,
        "degradation_mode": degradation_mode,
        "warnings": [],
        "errors": [],
    }

    logger.info(
        "[ground_draft_report] START — draft_report type=%s, paper_cards=%d",
        type(draft_report).__name__,
        len(paper_cards or []),
    )

    for node in (resolve_citations, verify_claims, format_output):
        try:
            patch = node(state)
        except Exception as exc:
            logger.warning("[ground_draft_report] %s failed: %s", node.__name__, exc)
            continue

        if not isinstance(patch, dict):
            continue

        state.update(patch)

    # Return only the keys that _apply_research_state cares about
    result: dict[str, Any] = {}
    for key in ("resolved_report", "verified_report", "final_report", "draft_markdown", "full_markdown"):
        val = state.get(key)
        if val is not None:
            result[key] = val

    # 关键：draft_report 也返回（包含 verified claims + resolved citations）
    draft_val = state.get("draft_report")
    if draft_val is not None:
        result["draft_report"] = draft_val

    return result

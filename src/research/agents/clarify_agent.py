"""ClarifyAgent service — schema-bound research brief generation."""

from __future__ import annotations

import json
import logging
from enum import Enum
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm import build_chat_llm
from src.agent.report_frame import extract_json_block, extract_llm_text
from src.agent.settings import Settings
from src.research.policies.clarify_policy import is_brief_valid, to_limited_brief
from src.research.prompts.clarify_prompt import (
    CLARIFY_REPAIR_PROMPT,
    CLARIFY_SYSTEM_PROMPT,
    FEW_SHOT_EXAMPLES,
    build_clarify_user_prompt,
)
from src.research.research_brief import ClarifyInput, ClarifyResult, ResearchBrief

logger = logging.getLogger(__name__)


class ParseStrategy(str, Enum):
    """Hierarchy of parsing strategies tried in order."""

    STRUCTURED_OUTPUT = "structured_output"
    JSON_PARSE = "json_parse"
    REPAIR = "repair"
    LIMITED = "limited"


def _emit_progress(emit_progress: Callable[[str], None] | None, message: str) -> None:
    if emit_progress:
        emit_progress(message)


def _invoke_with_few_shot(
    settings: Settings, user_prompt: str, max_tokens: int = 8192
) -> str:
    """Send system + few-shot + user to LLM, return raw text."""
    llm = build_chat_llm(settings, max_tokens=max_tokens)
    messages = [
        SystemMessage(content=CLARIFY_SYSTEM_PROMPT),
        SystemMessage(content=FEW_SHOT_EXAMPLES),
        HumanMessage(content=user_prompt),
    ]
    resp = llm.invoke(messages)
    return extract_llm_text(resp)


def _try_structured_output(settings: Settings, user_prompt: str) -> ResearchBrief | None:
    """Try provider-native structured output. Returns None if unsupported."""
    try:
        llm = build_chat_llm(settings, max_tokens=8192)
        structured = llm.with_structured_output(ResearchBrief, method="json_mode")
        brief = structured.invoke([HumanMessage(content=user_prompt)])
        return brief
    except Exception as exc:
        logger.debug("Structured output not available (%s): %s", type(exc).__name__, exc)
        return None


def _try_json_parse(raw_text: str) -> ResearchBrief | None:
    """Parse raw LLM text as JSON → Pydantic model. Returns None on failure."""
    try:
        data = json.loads(extract_json_block(raw_text))
        return ResearchBrief.model_validate(data)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.debug("JSON parse failed: %s", exc)
        return None


def _try_repair(settings: Settings, bad_output: str) -> ResearchBrief | None:
    """Attempt to repair malformed output with a second LLM call."""
    try:
        prompt = CLARIFY_REPAIR_PROMPT.format(bad_output=bad_output)
        repaired_text = _invoke_with_few_shot(settings, prompt, max_tokens=4096)
        return _try_json_parse(repaired_text)
    except Exception as exc:
        logger.debug("Repair call failed: %s", exc)
        return None


def run(
    input: ClarifyInput,
    emit_progress: Callable[[str], None] | None = None,
) -> ClarifyResult:
    """Main entry point — convert a raw research request to a ResearchBrief.

    Execution order:
      1. structured_output  (provider-native, preferred)
      2. json_parse          (JSON + Pydantic validation)
      3. repair              (second LLM call to fix malformed output)
      4. limited_brief       (conservative fallback, never crashes)

    Parameters
    ----------
    input : ClarifyInput
        Raw user query plus optional hints / context.

    Returns
    -------
    ClarifyResult
        brief   — valid ResearchBrief
        warnings — non-fatal notices (low confidence, significant ambiguity, etc.)
        raw_model_output — raw LLM text for debugging / thinking panel
    """
    settings = Settings.from_env()
    user_prompt = build_clarify_user_prompt(input)
    raw_text: str | None = None
    strategy_used: ParseStrategy = ParseStrategy.LIMITED
    warnings: list[str] = []

    # ── Strategy 1: provider-native structured output ──────────────────────
    _emit_progress(emit_progress, "Starting clarify pass from raw research query.")
    _emit_progress(emit_progress, "Trying provider-native structured output for ResearchBrief.")
    brief = _try_structured_output(settings, user_prompt)
    if brief is not None:
        strategy_used = ParseStrategy.STRUCTURED_OUTPUT
        _emit_progress(emit_progress, "Structured output succeeded.")
    else:
        _emit_progress(emit_progress, "Structured output unavailable; falling back to JSON generation.")

    # ── Strategy 2: JSON parse ────────────────────────────────────────────
    if brief is None:
        try:
            _emit_progress(emit_progress, "Calling LLM for JSON-format brief.")
            raw_text = _invoke_with_few_shot(settings, user_prompt)
            brief = _try_json_parse(raw_text)
            if brief is not None:
                strategy_used = ParseStrategy.JSON_PARSE
                _emit_progress(emit_progress, "JSON parse succeeded.")
            else:
                _emit_progress(emit_progress, "JSON parse failed; attempting repair pass.")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"JSON generation failed: {type(exc).__name__}: {exc}")
            _emit_progress(
                emit_progress,
                f"JSON generation failed with {type(exc).__name__}; continuing to fallback strategy.",
            )

    # ── Strategy 3: repair ────────────────────────────────────────────────
    if brief is None and raw_text is not None:
        repaired = _try_repair(settings, raw_text)
        if repaired is not None:
            brief = repaired
            strategy_used = ParseStrategy.REPAIR
            _emit_progress(emit_progress, "Repair pass produced a valid brief.")
            warnings.append(
                "LLM output was malformed and required repair; "
                "some fields may be approximated."
            )
        else:
            _emit_progress(emit_progress, "Repair pass failed; using conservative fallback brief.")

    # ── Strategy 4: limited brief ────────────────────────────────────────
    if brief is None:
        brief = to_limited_brief(input.raw_query)
        strategy_used = ParseStrategy.LIMITED
        _emit_progress(emit_progress, "Falling back to limited brief with needs_followup=True.")
        warnings.append(
            "All parsing strategies failed; returning a conservative limited brief. "
            "needs_followup is set to True."
        )

    # ── Post-validation ──────────────────────────────────────────────────
    if not is_brief_valid(brief):
        warnings.append(
            f"Brief produced by strategy '{strategy_used.value}' failed post-validation; "
            "falling back to limited brief."
        )
        brief = to_limited_brief(input.raw_query)

    # ── Confidence-based warnings ────────────────────────────────────────
    if brief.confidence < 0.5:
        warnings.append(
            f"Low confidence score ({brief.confidence:.2f}); "
            "ambiguities may need human resolution."
        )
    if brief.needs_followup:
        warnings.append(
            "Brief has needs_followup=True; downstream planning should wait for "
            "human clarification or explicit disambiguation."
        )

    _emit_progress(
        emit_progress,
        f"Clarify finished with strategy={strategy_used.value}, confidence={brief.confidence:.2f}.",
    )

    return ClarifyResult(
        brief=brief,
        warnings=warnings,
        raw_model_output=raw_text,
    )

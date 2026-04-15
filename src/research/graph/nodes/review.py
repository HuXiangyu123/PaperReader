"""Review node — Phase 3: 生成 ReviewFeedback。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any

from src.models.review import CoverageGap, ReviewFeedback, ReviewIssue, ReviewSeverity
from src.research.services.reviewer import ReviewerService
from src.research.services.grounding import ground_draft_report
from src.tasking.trace_wrapper import trace_node, trace_tool, get_trace_store

logger = logging.getLogger(__name__)

_reviewer = ReviewerService()


def _run_reviewer_sync(**kwargs) -> ReviewFeedback:
    """Execute the async reviewer from both plain sync code and loop-backed contexts."""

    def _runner() -> ReviewFeedback:
        return asyncio.run(_reviewer.review(**kwargs))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _runner()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_runner).result()


@trace_node(node_name="review", stage="review", store=get_trace_store())
def review_node(state: dict) -> dict:
    """
    Phase 3 review 节点。

    从 state 中读取：
    - rag_result
    - paper_cards
    - report_draft

    写入 state：
    - review_feedback: ReviewFeedback
    - review_passed: bool
    """
    task_id = str(state.get("task_id", ""))
    workspace_id = str(state.get("workspace_id", ""))
    rag_result = state.get("rag_result")
    paper_cards = state.get("paper_cards") or []
    draft_report = state.get("draft_report")
    report_draft = draft_report or state.get("draft_markdown")
    grounding_result: dict[str, Any] = {}
    grounding_warnings: list[str] = []

    if draft_report is not None:
        import logging as _logging
        _logger = _logging.getLogger(__name__)
        _logger.debug(
            "[review_node] before grounding: paper_cards=%d, draft_report type=%s",
            len(paper_cards),
            type(draft_report).__name__,
        )
        try:
            grounding_result = ground_draft_report(
                draft_report,
                paper_cards=paper_cards,
                report_mode=str(state.get("report_mode", "draft") or "draft"),
                degradation_mode=str(state.get("degradation_mode", "normal") or "normal"),
            )
            report_draft = (
                grounding_result.get("verified_report")
                or grounding_result.get("final_report")
                or draft_report
            )
            grounding_warnings = [
                str(item) for item in grounding_result.get("warnings", []) if item
            ]
        except Exception as exc:
            logger.exception("[review_node] grounding failed: %s", exc)
            grounding_warnings = [f"grounding failed: {exc}"]

    logger.info(
        f"[review_node] task={task_id} "
        f"rag_result={rag_result is not None} "
        f"paper_cards={len(paper_cards)}"
    )

    # 如果没有 paper_cards 和 draft，发出警告而非继续生成空报告
    if not paper_cards and not draft_report and not report_draft:
        logger.warning(
            "[review_node] no paper_cards and no draft_report — "
            "search/extract/draft pipeline likely failed. Returning early."
        )
        return {
            "review_feedback": ReviewFeedback(
                task_id=task_id,
                workspace_id=workspace_id,
                passed=False,
                summary="No paper_cards available: the search or extract pipeline failed. "
                        "The draft cannot be generated. Please retry with a more specific topic.",
                issues=[
                    ReviewIssue(
                        severity=ReviewSeverity.BLOCKER,
                        category=ReviewCategory.COVERAGE_GAP,
                        target="paper_cards",
                        summary="检索阶段未返回任何论文，可能是查询不相关或服务不可用",
                    ),
                ],
                coverage_gaps=[
                    CoverageGap(
                        missing_topics=["检索结果为空", "无有效 PaperCards"],
                        note="建议使用更具体的研究主题（包含英文技术术语），并确保 SearXNG/arXiv API 服务正常",
                    ),
                ],
            ),
            "review_passed": False,
        }

    # Run reviewer synchronously (LLM calls inside ReviewerService)
    try:
        feedback = _run_reviewer_sync(
            task_id=task_id,
            workspace_id=workspace_id,
            rag_result=rag_result,
            paper_cards=paper_cards,
            report_draft=report_draft,
        )
    except Exception as exc:
        logger.exception(f"[review_node] reviewer failed: {exc}")
        # Fallback: create a minimal failed feedback
        feedback = ReviewFeedback(
            task_id=task_id,
            workspace_id=workspace_id,
            passed=False,
            summary=f"Reviewer service error: {exc}",
        )

    result = {
        **grounding_result,
        "review_feedback": feedback,
        "review_passed": feedback.passed,
    }
    if grounding_warnings:
        result["warnings"] = grounding_warnings
    return result

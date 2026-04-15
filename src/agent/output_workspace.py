"""Output workspace — file-based task working directory.

Each task gets an isolated directory under ``output/<task_id>/`` that persists
intermediate artifacts (brief, search_plan, paper_cards, draft, review feedback,
revisions, and the final report). PostgreSQL continues to hold the task index
and state; the workspace directory serves as the durable writing workspace for
the report generation process.

Directory structure::

    output/
      <task_id>/
        metadata.json          — task metadata (created by create_workspace)
        brief.json             — clarify node output
        search_plan.json       — search_plan node output
        rag_result.json        — search/retrieval output
        paper_cards.json       — extract node output
        draft.md               — draft report (markdown)
        review_feedback.json   — review node output
        revisions/
          001_initial.md       — first draft revision
          002_after_review.md  — revision after first review
          ...
        report.md              — final report (written on completion)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Root output directory — configurable via environment variable
OUTPUT_ROOT = Path(os.environ.get("PAPERREADER_OUTPUT_ROOT", "output"))


def get_workspace_path(task_id: str) -> Path:
    """Return the workspace directory for a task."""
    return OUTPUT_ROOT / task_id


def create_workspace(task_id: str, metadata: dict[str, Any]) -> Path:
    """
    Create the task workspace directory and write initial metadata.

    Idempotent: if the directory already exists, this is a no-op.
    """
    workspace = get_workspace_path(task_id)
    workspace.mkdir(parents=True, exist_ok=True)

    # Ensure subdirectories exist
    (workspace / "revisions").mkdir(parents=True, exist_ok=True)

    metadata_path = workspace / "metadata.json"
    if not metadata_path.exists():
        _write_json(metadata_path, {
            "task_id": task_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **metadata,
        })
        logger.debug("[output_workspace] created %s", workspace)

    return workspace


def write_brief(task_id: str, brief: dict[str, Any]) -> Path:
    """Write the clarify node output."""
    return _write_json(task_id, "brief.json", brief)


def write_search_plan(task_id: str, search_plan: dict[str, Any]) -> Path:
    """Write the search_plan node output."""
    return _write_json(task_id, "search_plan.json", search_plan)


def write_rag_result(task_id: str, rag_result: dict[str, Any]) -> Path:
    """Write the search/retrieval output."""
    return _write_json(task_id, "rag_result.json", rag_result)


def write_paper_cards(task_id: str, paper_cards: list[dict[str, Any]]) -> Path:
    """Write the extract node output."""
    return _write_json(task_id, "paper_cards.json", paper_cards)


def write_draft(task_id: str, draft_markdown: str) -> Path:
    """Write the draft report markdown."""
    workspace = get_workspace_path(task_id)
    path = workspace / "draft.md"
    path.write_text(draft_markdown, encoding="utf-8")
    logger.debug("[output_workspace] wrote draft.md (%d chars)", len(draft_markdown))
    return path


def write_review_feedback(task_id: str, review_feedback: dict[str, Any]) -> Path:
    """Write the review node output."""
    return _write_json(task_id, "review_feedback.json", review_feedback)


def write_draft_report(task_id: str, draft_report: dict[str, Any]) -> Path:
    """Write the structured draft report (DraftReport JSON)."""
    return _write_json(task_id, "draft_report.json", draft_report)


def append_revision(task_id: str, revision_markdown: str, label: str | None = None) -> Path:
    """
    Append a new revision to the revisions/ directory.

    Files are named as ``<3-digit index>_<label>.md``, e.g. ``001_initial.md``,
    ``002_after_review.md``. The label is inferred from the revision content
    when not provided.
    """
    workspace = get_workspace_path(task_id)
    revisions_dir = workspace / "revisions"
    revisions_dir.mkdir(parents=True, exist_ok=True)

    # Find next revision number
    existing = sorted(revisions_dir.glob("*.md"))
    next_num = len(existing) + 1

    # Infer label from first meaningful line
    if label is None:
        label = _infer_revision_label(revision_markdown)

    filename = f"{next_num:03d}_{label}.md"
    path = revisions_dir / filename
    path.write_text(revision_markdown, encoding="utf-8")
    logger.info("[output_workspace] appended revision %s", path.relative_to(OUTPUT_ROOT))
    return path


def write_report(task_id: str, report_markdown: str) -> Path:
    """
    Write the final report to ``report.md``.

    Also copies the last revision from revisions/ as ``report.md``.
    """
    workspace = get_workspace_path(task_id)
    path = workspace / "report.md"
    path.write_text(report_markdown, encoding="utf-8")

    # Update metadata with completed_at
    metadata_path = workspace / "metadata.json"
    if metadata_path.exists():
        metadata = _read_json(metadata_path)
        metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(metadata_path, metadata)

    logger.info("[output_workspace] wrote report.md (%d chars)", len(report_markdown))
    return path


def write_node_output(task_id: str, node_name: str, node_result: Any) -> Path | None:
    """
    Write a node's output to the task workspace directory.

    Dispatches based on node_name, extracting the relevant field from the
    full node_result dict (which may contain metadata like _backend_mode, etc).
    """
    if node_name == "clarify":
        brief = node_result.get("brief") if isinstance(node_result, dict) else None
        return write_brief(task_id, brief) if brief else None
    elif node_name == "search_plan":
        plan = node_result.get("search_plan") if isinstance(node_result, dict) else None
        return write_search_plan(task_id, plan) if plan else None
    elif node_name == "search":
        rag = node_result.get("rag_result") if isinstance(node_result, dict) else None
        return write_rag_result(task_id, rag) if rag else None
    elif node_name == "extract":
        cards = node_result.get("paper_cards") if isinstance(node_result, dict) else None
        return write_paper_cards(task_id, cards) if cards else None
    elif node_name == "draft":
        if isinstance(node_result, dict):
            md = node_result.get("draft_markdown")
            dr = node_result.get("draft_report")
            if md:
                return write_draft(task_id, md)
            elif dr:
                return write_draft_report(task_id, dr)
        elif isinstance(node_result, str):
            return write_draft(task_id, node_result)
        return None
    elif node_name == "review":
        fb = node_result.get("review_feedback") if isinstance(node_result, dict) else None
        return write_review_feedback(task_id, fb) if fb else None
    else:
        logger.debug("[output_workspace] no canonical file for node %s", node_name)
        return None


def list_revisions(task_id: str) -> list[Path]:
    """Return sorted list of revision file paths."""
    workspace = get_workspace_path(task_id)
    revisions_dir = workspace / "revisions"
    if not revisions_dir.is_dir():
        return []
    return sorted(revisions_dir.glob("*.md"))


def get_workspace_summary(task_id: str) -> dict[str, Any]:
    """Return a summary of what's in the workspace."""
    workspace = get_workspace_path(task_id)
    if not workspace.is_dir():
        return {"exists": False, "task_id": task_id}

    files = {p.name: p.stat().st_size for p in workspace.rglob("*") if p.is_file()}
    revisions = [
        {"name": p.name, "size": p.stat().st_size}
        for p in sorted((workspace / "revisions").glob("*.md"))
    ]

    return {
        "exists": True,
        "task_id": task_id,
        "path": str(workspace),
        "files": files,
        "revision_count": len(revisions),
        "revisions": revisions,
    }


# ─── helpers ───────────────────────────────────────────────────────────────────


def _write_json(task_id: str, filename: str, data: Any) -> Path:
    workspace = get_workspace_path(task_id)
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / filename
    _write_json_to_path(path, data)
    return path


def _write_json_to_path(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_revision_label(text: str) -> str:
    """Infer a short label from the revision content."""
    first_line = text.strip().split("\n")[0][:40] if text.strip() else "revision"
    # Replace spaces/special chars
    label = "".join(c if c.isalnum() else "_" for c in first_line)
    return label.lower()[:30] or "revision"

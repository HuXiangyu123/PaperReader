from __future__ import annotations

from src.models.report import Citation, DraftReport, ResolvedReport
from src.verification.source_tiers import classify_url
from src.verification.reachability import check_url_reachable_sync


def _fetch_content_snippet(url: str, max_chars: int = 2000) -> str | None:
    """Fetch text content from a URL for evidence verification."""
    try:
        import httpx

        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            text = resp.text[:max_chars]
            return text if text.strip() else None
    except Exception:
        return None


def resolve_citations(state: dict) -> dict:
    """Resolve each citation: classify tier, check reachability, fetch content."""
    draft: DraftReport | None = state.get("draft_report")
    if not draft:
        return {"warnings": ["resolve_citations: no draft_report, skipping"]}

    resolved_citations: list[Citation] = []
    warnings: list[str] = []

    for cit in draft.citations:
        tier = classify_url(cit.url)
        reachable = check_url_reachable_sync(cit.url)

        fetched = None
        if reachable:
            fetched = _fetch_content_snippet(cit.url)

        resolved_cit = cit.model_copy(
            update={
                "source_tier": tier,
                "reachable": reachable,
                "fetched_content": fetched,
            }
        )
        resolved_citations.append(resolved_cit)

        if not reachable:
            warnings.append(
                f"resolve_citations: unreachable URL {cit.label} ({cit.url})"
            )

    resolved = ResolvedReport(
        sections=dict(draft.sections),
        claims=list(draft.claims),
        citations=resolved_citations,
    )

    result: dict = {"resolved_report": resolved}
    if warnings:
        result["warnings"] = warnings
    return result

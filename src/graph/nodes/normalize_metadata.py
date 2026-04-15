from __future__ import annotations

from src.models.paper import NormalizedDocument, PaperMetadata


def normalize_metadata(state: dict) -> dict:
    source_type = state.get("source_type")
    manifest = state.get("source_manifest") or {}
    pdf_text = state.get("pdf_text") or ""

    if source_type == "arxiv":
        metadata = PaperMetadata(
            title=manifest.get("title", "Unknown"),
            authors=manifest.get("authors", []),
            abstract=manifest.get("abstract", ""),
            pdf_url=manifest.get("pdf_url"),
            published=manifest.get("published"),
        )
    else:
        lines = pdf_text.strip().split("\n")
        title = lines[0].strip() if lines else "Untitled"
        metadata = PaperMetadata(
            title=title,
            authors=[],
            abstract=pdf_text[:500],
        )

    if not pdf_text and not metadata.abstract:
        return {
            "errors": ["normalize_metadata: no document text and no abstract available"],
            "degradation_mode": "safe_abort",
        }

    doc = NormalizedDocument(
        metadata=metadata,
        document_text=pdf_text,
        document_sections={},
        source_manifest=manifest,
    )
    return {"normalized_doc": doc}

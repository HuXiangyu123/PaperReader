from __future__ import annotations

import httpx

from src.tools.pdf import extract_text_from_pdf_bytes


def extract_document_text(state: dict) -> dict:
    source_type = state.get("source_type")

    if source_type == "pdf":
        if state.get("pdf_text"):
            return {}
        return {"errors": ["extract_document_text: source_type is pdf but pdf_text is empty"]}

    manifest = state.get("source_manifest") or {}
    pdf_url = manifest.get("pdf_url")
    if not pdf_url:
        return {
            "warnings": ["extract_document_text: no pdf_url in manifest, using abstract only"],
            "degradation_mode": "limited",
        }

    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            resp = client.get(pdf_url)
            resp.raise_for_status()
        text = extract_text_from_pdf_bytes(resp.content)
        if text.startswith("Error"):
            return {
                "warnings": [f"extract_document_text: PDF parse failed: {text[:200]}"],
                "degradation_mode": "limited",
            }
        return {"pdf_text": text}
    except Exception as e:
        return {
            "warnings": [f"extract_document_text: download failed: {e}"],
            "degradation_mode": "limited",
        }

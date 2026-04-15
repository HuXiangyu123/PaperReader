from __future__ import annotations

from src.tools.arxiv_paper import _extract_arxiv_id


def input_parse(state: dict) -> dict:
    raw = state.get("raw_input", "")
    pdf_text = state.get("pdf_text")

    if pdf_text:
        return {"source_type": "pdf"}

    arxiv_id = _extract_arxiv_id(raw)
    if arxiv_id:
        return {"source_type": "arxiv", "arxiv_id": arxiv_id}

    return {"errors": [f"input_parse: cannot determine source type from '{raw[:100]}'"]}

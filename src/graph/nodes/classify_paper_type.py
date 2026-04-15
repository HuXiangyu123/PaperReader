from __future__ import annotations


SURVEY_KEYWORDS = (
    "survey",
    "review",
    "overview",
    "systematic review",
    "a survey of",
    "taxonomy",
)


def classify_paper_type(state: dict) -> dict:
    doc = state.get("normalized_doc")
    if not doc:
        return {"warnings": ["classify_paper_type: no normalized_doc, defaulting to regular"], "paper_type": "regular"}

    title = (doc.metadata.title or "").lower()
    abstract = (doc.metadata.abstract or "").lower()
    haystack = f"{title}\n{abstract}"

    if any(keyword in haystack for keyword in SURVEY_KEYWORDS):
        return {"paper_type": "survey"}
    return {"paper_type": "regular"}

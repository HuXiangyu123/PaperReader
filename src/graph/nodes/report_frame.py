from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.report_frame import REGULAR_FULL_SYSTEM_PROMPT, extract_llm_text, parse_json_object
from src.models.report import Citation, Claim, DraftReport, ReportFrame


def report_frame(state: dict) -> dict:
    doc = state.get("normalized_doc")
    evidence = state.get("evidence")
    if not doc:
        return {"errors": ["report_frame: no normalized_doc"]}

    evidence_text = ""
    if evidence:
        for r in evidence.rag_results[:8]:
            evidence_text += f"[RAG] {r.text}\n\n"
        for w in evidence.web_results[:3]:
            evidence_text += f"[WEB {w.url}] {w.text[:1200]}\n\n"

    meta = doc.metadata
    user_prompt = (
        f"Title: {meta.title}\n"
        f"Authors: {', '.join(meta.authors)}\n"
        f"Published: {meta.published}\n"
        f"Abstract: {meta.abstract}\n\n"
        f"Full document text:\n{doc.document_text}\n\n"
        f"Evidence:\n{evidence_text}\n\n"
        "Generate the full report JSON."
    )

    try:
        from src.agent.settings import Settings
        from src.agent.llm import build_chat_llm

        settings = Settings.from_env()
        llm = build_chat_llm(settings, max_tokens=16384)
        resp = llm.invoke([
            SystemMessage(content=REGULAR_FULL_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        reasoning = (getattr(resp, "additional_kwargs", None) or {}).get("reasoning_content", "")
        text = extract_llm_text(resp)
        data = parse_json_object(text)

        claims = [
            Claim(id=c["id"], text=c["text"], citation_labels=c.get("citation_labels", []))
            for c in data.get("claims", [])
        ]
        citations = [
            Citation(label=c["label"], url=c["url"], reason=c.get("reason", ""))
            for c in data.get("citations", [])
        ]
        sections = {k: v for k, v in data.get("sections", {}).items() if isinstance(v, str)}

        frame = ReportFrame(
            title=meta.title,
            paper_type="regular",
            mode="full",
            sections=sections,
            outline=None,
            claims=claims,
            citations=citations,
        )
        draft = DraftReport(sections=sections, claims=claims, citations=citations)
        result: dict = {"report_frame": frame, "draft_report": draft}
        if reasoning:
            result["_reasoning_content"] = reasoning
        return result
    except Exception as e:
        return {"errors": [f"report_frame: {e}"]}

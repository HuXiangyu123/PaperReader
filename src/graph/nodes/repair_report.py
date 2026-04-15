from __future__ import annotations

REQUIRED_SECTIONS = {"标题", "核心贡献", "方法概述", "关键实验", "局限性"}


def repair_report(state: dict) -> dict:
    report = state.get("draft_report")
    if not report:
        return {"warnings": ["repair_report: no draft_report, skipping"]}

    existing = set(report.sections.keys())
    missing = REQUIRED_SECTIONS - existing

    if not missing and len(report.citations) > 0:
        return {}

    try:
        import json

        from langchain_core.messages import HumanMessage, SystemMessage

        from src.agent.settings import Settings
        from src.agent.llm import build_deepseek_chat

        settings = Settings.from_env()
        llm = build_deepseek_chat(settings)

        current_sections = json.dumps(report.sections, ensure_ascii=False, indent=2)
        repair_prompt = (
            f"The following report is missing these sections: {', '.join(missing) if missing else 'none'}.\n"
            f"It has {len(report.citations)} citations"
            f"{' (needs at least 1)' if not report.citations else ''}.\n\n"
            f"Current sections:\n{current_sections}\n\n"
            "Add the missing sections and/or citations. "
            "Output ONLY a JSON object with keys 'sections' and 'citations'."
        )

        from src.agent.report_frame import extract_llm_text, parse_json_object

        resp = llm.invoke([
            SystemMessage(content="You repair incomplete literature reports. Output valid JSON only."),
            HumanMessage(content=repair_prompt),
        ])
        text = extract_llm_text(resp)
        data = parse_json_object(text)
        if "sections" in data:
            merged = {**report.sections, **data["sections"]}
            report = report.model_copy(update={"sections": merged})
        if "citations" in data and not report.citations:
            from src.models.report import Citation

            new_cites = [
                Citation(label=c["label"], url=c["url"], reason=c.get("reason", ""))
                for c in data["citations"]
            ]
            report = report.model_copy(update={"citations": new_cites})

        return {"draft_report": report, "warnings": ["repair_report: repair pass triggered"]}

    except Exception as e:
        return {"warnings": [f"repair_report: repair failed ({e}), continuing with incomplete report"]}

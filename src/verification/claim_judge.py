from __future__ import annotations

import json

from src.models.report import ClaimSupport

JUDGE_SYSTEM_PROMPT = """You are a claim-evidence verification judge. Given a claim and evidence text from a citation, determine if the evidence supports the claim.

Output JSON only:
{
  "support_status": "supported" | "partial" | "unsupported" | "unverifiable",
  "evidence_excerpt": "relevant quote from evidence (max 200 chars)",
  "reason": "brief explanation",
  "confidence": 0.0-1.0
}
"""


def judge_claim_citation(
    claim_id: str,
    claim_text: str,
    citation_label: str,
    citation_content: str | None,
    llm=None,
) -> ClaimSupport:
    """Judge whether citation evidence supports a claim.

    If no content available or no LLM, returns 'unverifiable'.
    """
    if not citation_content or not citation_content.strip():
        return ClaimSupport(
            claim_id=claim_id,
            citation_label=citation_label,
            support_status="unverifiable",
            reason="No citation content available for verification",
        )

    if llm is None:
        return ClaimSupport(
            claim_id=claim_id,
            citation_label=citation_label,
            support_status="unverifiable",
            reason="No LLM available for judgment",
        )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        user_prompt = (
            f"Claim: {claim_text}\n\n"
            f"Evidence from {citation_label}:\n{citation_content[:3000]}\n\n"
            "Judge whether the evidence supports the claim. Output JSON only."
        )

        resp = llm.invoke([
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        text = resp.content.strip()

        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        return ClaimSupport(
            claim_id=claim_id,
            citation_label=citation_label,
            support_status=data.get("support_status", "unverifiable"),
            evidence_excerpt=data.get("evidence_excerpt"),
            reason=data.get("reason"),
            judge_confidence=data.get("confidence"),
        )
    except Exception as e:
        return ClaimSupport(
            claim_id=claim_id,
            citation_label=citation_label,
            support_status="unverifiable",
            reason=f"Judge error: {e}",
        )

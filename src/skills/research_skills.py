"""Research Skills — 5 个 ARIS 风格科研 skill 函数实现。

每个函数对应一个 SKILL.md，backed by LOCAL_FUNCTION handler。
严格遵循 OpenCode 风格：
- 输入：dict（来自 agent 的 structured inputs）
- 输出：dict（带 summary + output + artifacts）
- 错误：返回带 error 字段的 dict
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ─── Skill 1: lit_review_scanner ───────────────────────────────────────────────


def lit_review_scanner(inputs: dict[str, Any], context: dict) -> dict:
    """
    Multi-source academic literature scan and candidate ranking.

    inputs:
        topic: str — research topic
        sub_questions: list[str] — sub-questions to cover
        max_results: int (default: 30)
        year_filter: str (optional)

    returns:
        summary: str
        paper_candidates: list[dict]
        search_queries: list[str]
    """
    topic = inputs.get("topic", "")
    sub_questions = inputs.get("sub_questions", [])
    max_results = inputs.get("max_results", 30)
    year_filter = inputs.get("year_filter", "")

    if not topic:
        return {"error": "lit_review_scanner: topic is required"}

    try:
        from src.tools.search_tools import _searxng_search

        all_hits: list[dict] = []
        queries = [topic]
        if sub_questions:
            queries.extend(sub_questions[:5])

        for query in queries:
            result = _searxng_search(
                query,
                engines="arxiv",
                max_results=max(5, max_results // len(queries)),
            )
            if result.get("ok"):
                all_hits.extend(result.get("hits", []))

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_hits: list[dict] = []
        for hit in all_hits:
            url = hit.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_hits.append(hit)

        candidates = []
        for i, hit in enumerate(unique_hits[:max_results], 1):
            candidates.append({
                "rank": i,
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
                "abstract": hit.get("content", "")[:500],
                "engine": hit.get("engine", "arxiv"),
                "published_date": hit.get("publishedDate"),
            })

        summary = (
            f"扫描完成：{len(queries)} 个查询，"
            f"去重后 {len(candidates)} 篇候选论文"
        )
        return {
            "summary": summary,
            "paper_candidates": candidates,
            "search_queries": queries,
            "total_found": len(unique_hits),
            "dedup_strategy": "url_exact",
        }

    except Exception as exc:
        logger.exception("lit_review_scanner failed: %s", exc)
        return {"error": f"lit_review_scanner failed: {exc}"}


# ─── Skill 2: claim_verification ────────────────────────────────────────────────


def claim_verification(inputs: dict[str, Any], context: dict) -> dict:
    """
    Verify scientific claims against retrieved evidence.

    inputs:
        draft_report: dict — must contain claims and citations
        evidence_sources: list[dict] — optional external evidence
        claim_ids: list[str] (optional) — verify specific claims only

    returns:
        summary: str
        verified_claims: list[dict]
        grounding_stats: dict
    """
    draft_report = inputs.get("draft_report")
    if not draft_report:
        return {"error": "claim_verification: draft_report is required"}

    claims = draft_report.get("claims", [])
    citations = draft_report.get("citations", [])

    if not claims:
        return {
            "summary": "No claims to verify",
            "verified_claims": [],
            "grounding_stats": {"total": 0, "grounded": 0, "partial": 0, "ungrounded": 0},
        }

    cit_map: dict[str, dict] = {
        c.get("label", ""): c for c in citations
    }

    try:
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=8192)

        verified_claims = []
        grounded_count = 0
        partial_count = 0
        ungrounded_count = 0

        VERIFY_SYSTEM = """You are a claim verification expert. Given a claim and its cited evidence, judge whether the claim is:
- "grounded": the citation fully supports the claim
- "partial": the citation partially supports the claim
- "ungrounded": the citation does not support the claim
- "abstained": cannot judge due to insufficient evidence

Output strictly JSON: {"status": "...", "reason": "...", "confidence": 0.0-1.0}"""

        for claim in claims:
            claim_id = claim.get("id", "")
            claim_text = claim.get("text", "")
            citation_labels = claim.get("citation_labels", [])

            # Gather cited evidence
            evidence_parts = []
            for label in citation_labels:
                cit = cit_map.get(label)
                if cit:
                    content = cit.get("fetched_content") or cit.get("reason", "")
                    if content:
                        evidence_parts.append(f"[{label}] {content[:500]}")

            if not evidence_parts:
                verified_claims.append({
                    "claim_id": claim_id,
                    "text": claim_text,
                    "status": "abstained",
                    "reason": "No reachable citation content",
                    "confidence": 0.0,
                })
                continue

            evidence_text = "\n".join(evidence_parts)
            user_prompt = f"""Claim: {claim_text}

Evidence:\n{evidence_text}

Judge the claim against the evidence. Output JSON:"""
            try:
                resp = llm.invoke([
                    SystemMessage(content=VERIFY_SYSTEM),
                    HumanMessage(content=user_prompt),
                ])
                raw = resp.content if hasattr(resp, "content") else str(resp)
                data = _extract_json(raw)
                status = data.get("status", "ungrounded")
            except Exception:
                status = "ungrounded"

            if status == "grounded":
                grounded_count += 1
            elif status == "partial":
                partial_count += 1
            else:
                ungrounded_count += 1

            verified_claims.append({
                "claim_id": claim_id,
                "text": claim_text,
                "status": status,
                "reason": data.get("reason", ""),
                "confidence": data.get("confidence", 0.0),
                "cited_labels": citation_labels,
            })

        total = len(verified_claims)
        grounded_ratio = grounded_count / total if total else 0.0
        return {
            "summary": (
                f"验证了 {total} 条 claims："
                f"{grounded_count} grounded, {partial_count} partial, "
                f"{ungrounded_count} ungrounded"
            ),
            "verified_claims": verified_claims,
            "grounding_stats": {
                "total": total,
                "grounded": grounded_count,
                "partial": partial_count,
                "ungrounded": ungrounded_count,
                "grounded_ratio": round(grounded_ratio, 3),
            },
        }

    except Exception as exc:
        logger.exception("claim_verification failed: %s", exc)
        return {"error": f"claim_verification failed: {exc}"}


# ─── Skill 3: comparison_matrix_builder ───────────────────────────────────────


def comparison_matrix_builder(inputs: dict[str, Any], context: dict) -> dict:
    """
    Build a structured comparison matrix from paper cards.

    inputs:
        paper_cards: list[dict]
        compare_dimensions: list[str] (default: methods, datasets, benchmarks, limitations)
        format: "table" | "json" (default: "table")

    returns:
        summary: str
        matrix: list[dict]  — one row per paper, columns = dimensions
        missing_fields: list[str]  — papers with missing info
    """
    paper_cards = inputs.get("paper_cards", [])
    dimensions = inputs.get("compare_dimensions", [
        "methods", "datasets", "benchmarks", "limitations"
    ])
    output_format = inputs.get("format", "table")

    if not paper_cards:
        return {"error": "comparison_matrix_builder: paper_cards is required"}

    try:
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=16384)

        # Prepare paper summaries for LLM
        papers_text = []
        for i, card in enumerate(paper_cards, 1):
            title = card.get("title", card.get("paper_title", f"Paper {i}"))
            abstract = card.get("summary", card.get("abstract", ""))
            methods = card.get("methods", [])
            datasets = card.get("datasets", [])
            papers_text.append(f"Paper {i}: {title}\nAbstract: {abstract[:300]}\nMethods: {methods}\nDatasets: {datasets}")

        SYSTEM = f"""You are a survey paper analyst. Given paper metadata, build a structured comparison matrix.

Output strictly JSON:
{{"rows": [
  {{"paper": "title", "methods": "...", "datasets": "...", "benchmarks": "...", "limitations": "..."}},
  ...
]}}"""

        user_prompt = (
            "Compare these papers across the following dimensions: "
            + ", ".join(dimensions) + "\n\n"
            + "\n\n".join(papers_text)
        )

        resp = llm.invoke([
            SystemMessage(content=SYSTEM),
            HumanMessage(content=user_prompt),
        ])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        data = _extract_json(raw) or {}

        rows = data.get("rows", [])
        missing = [
            card.get("title", f"Paper {i+1}")
            for i, card in enumerate(paper_cards)
            if not any(r.get("paper", "").lower() in card.get("title", "").lower()
                       for r in rows)
        ]

        if output_format == "json":
            matrix = rows
        else:
            # Table format for display
            header = ["Paper"] + dimensions
            table_lines = [" | ".join(header), "|".join(["---"] * len(header))]
            for row in rows:
                cells = [row.get("paper", ""), *[row.get(d, "") for d in dimensions]]
                table_lines.append(" | ".join(cells))
            matrix = {"header": header, "rows": rows, "table_text": "\n".join(table_lines)}

        return {
            "summary": f"对比矩阵构建完成：{len(rows)} 篇论文 × {len(dimensions)} 个维度",
            "matrix": matrix,
            "missing_fields": missing,
            "dimensions": dimensions,
        }

    except Exception as exc:
        logger.exception("comparison_matrix_builder failed: %s", exc)
        return {"error": f"comparison_matrix_builder failed: {exc}"}


# ─── Skill 4: experiment_replicator ─────────────────────────────────────────────


def experiment_replicator(inputs: dict[str, Any], context: dict) -> dict:
    """
    Analyze experimental settings and results from academic papers.

    inputs:
        paper_cards: list[dict]
        focus_papers: list[str] (optional) — arXiv IDs or titles to prioritize

    returns:
        summary: str
        experiments: list[dict]
        reproducibility_scores: dict
    """
    paper_cards = inputs.get("paper_cards", [])
    focus_papers = inputs.get("focus_papers", [])

    if not paper_cards:
        return {"error": "experiment_replicator: paper_cards is required"}

    try:
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=16384)

        papers_text = []
        for i, card in enumerate(paper_cards, 1):
            title = card.get("title", card.get("paper_title", f"Paper {i}"))
            abstract = card.get("summary", card.get("abstract", ""))
            papers_text.append(f"Paper {i}: {title}\nAbstract: {abstract[:500]}")

        SYSTEM = """You are a reproducibility analyst. Extract experimental settings from academic paper abstracts.

Output strictly JSON:
{"experiments": [
  {
    "paper": "title",
    "datasets": ["dataset1", "dataset2"],
    "metrics": ["metric1", "metric2"],
    "baselines": ["baseline1", "baseline2"],
    "hyperparameters": {"key": "value"},
    "reproducibility_score": 0.0-1.0,
    "missing_info": ["what is missing for full reproducibility"]
  }
]}"""

        user_prompt = (
            "Analyze these papers for experimental reproducibility:\n\n"
            + "\n\n".join(papers_text)
        )

        resp = llm.invoke([
            SystemMessage(content=SYSTEM),
            HumanMessage(content=user_prompt),
        ])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        data = _extract_json(raw) or {}

        experiments = data.get("experiments", [])
        scores = {
            e.get("paper", ""): e.get("reproducibility_score", 0.0)
            for e in experiments
        }
        avg_score = round(sum(scores.values()) / len(scores), 3) if scores else 0.0

        return {
            "summary": (
                f"分析了 {len(experiments)} 篇论文的实验设置，"
                f"平均可复现性评分：{avg_score}"
            ),
            "experiments": experiments,
            "reproducibility_scores": scores,
            "average_score": avg_score,
        }

    except Exception as exc:
        logger.exception("experiment_replicator failed: %s", exc)
        return {"error": f"experiment_replicator failed: {exc}"}


# ─── Skill 5: writing_scaffold_generator ───────────────────────────────────────


def writing_scaffold_generator(inputs: dict[str, Any], context: dict) -> dict:
    """
    Generate structured writing scaffold for academic survey papers.

    inputs:
        topic: str
        paper_cards: list[dict]
        comparison_matrix: dict (optional)
        desired_length: "short" | "medium" | "long" (default: "medium")

    returns:
        summary: str
        scaffold: dict
        outline: list[str]
    """
    topic = inputs.get("topic", "")
    paper_cards = inputs.get("paper_cards", [])
    comparison_matrix = inputs.get("comparison_matrix", {})
    desired_length = inputs.get("desired_length", "medium")

    if not topic:
        return {"error": "writing_scaffold_generator: topic is required"}

    try:
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=16384)

        papers_text = ""
        for i, card in enumerate(paper_cards[:10], 1):  # Limit to 10 papers
            title = card.get("title", f"Paper {i}")
            summary = card.get("summary", card.get("abstract", ""))
            methods = card.get("methods", [])
            papers_text += f"[{i}] {title}\n{summary[:300]}\nMethods: {methods}\n\n"

        length_map = {
            "short": "5-8 sentences per section, concise",
            "medium": "200-400 words per section, balanced depth",
            "long": "500-800 words per section, comprehensive",
        }
        length_desc = length_map.get(desired_length, length_map["medium"])

        SYSTEM = f"""You are an academic survey paper writing expert. Generate a structured writing scaffold.

Output strictly JSON:
{{"sections": {{
  "title": "Proposed Survey Title",
  "abstract": "150-word abstract",
  "introduction": ["paragraph outline 1", "paragraph outline 2", ...],
  "background": ["section outline 1", ...],
  "methods_review": ["method 1: description", "method 2: description", ...],
  "datasets_and_benchmarks": ["dataset 1: description", ...],
  "challenges_and_limitations": ["challenge 1", ...],
  "future_directions": ["direction 1", ...],
  "conclusion": "conclusion paragraph outline"
}},
"outline": ["Section 1 Title", "Section 1.1 Subsection", ...],
"writing_guidance": "guidance notes for authors"}}"""

        user_prompt = (
            f"Research topic: {topic}\n\n"
            f"Paper corpus ({len(paper_cards)} papers):\n{papers_text}\n\n"
            f"Desired section length: {length_desc}\n\n"
            "Generate a structured writing scaffold in JSON."
        )

        resp = llm.invoke([
            SystemMessage(content=SYSTEM),
            HumanMessage(content=user_prompt),
        ])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        data = _extract_json(raw) or {}

        scaffold = data.get("sections", {})
        outline = data.get("outline", [])

        return {
            "summary": (
                f"写作框架生成完成：{len(outline)} 个章节，"
                f"覆盖 {len(paper_cards)} 篇论文"
            ),
            "scaffold": scaffold,
            "outline": outline,
            "writing_guidance": data.get("writing_guidance", ""),
            "desired_length": desired_length,
        }

    except Exception as exc:
        logger.exception("writing_scaffold_generator failed: %s", exc)
        return {"error": f"writing_scaffold_generator failed: {exc}"}


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _extract_json(text: str) -> dict | None:
    """Extract first JSON object/dict from LLM output text."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try JSON block
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass
    return None

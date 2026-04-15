"""Draft node — Phase 2: 综合 PaperCards 生成综述草稿。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.models.report import Citation, Claim, DraftReport
from src.tasking.trace_wrapper import get_trace_store, trace_node

logger = logging.getLogger(__name__)


@trace_node(node_name="draft", stage="draft", store=get_trace_store())
def draft_node(state: dict) -> dict:
    """
    Phase 2 草稿节点。

    输入：state.paper_cards, state.brief
    输出：state.draft_report (DraftReport), state.draft_markdown (str)
    """
    paper_cards = state.get("paper_cards", [])
    brief = state.get("brief")

    if not paper_cards:
        logger.warning("[draft_node] no paper_cards, skipping")
        return {"draft_report": None, "draft_markdown": None}

    # ── 1. 构建结构化 DraftReport ────────────────────────────────
    draft_report = _build_draft_report(paper_cards, brief)

    # ── 2. 生成可读 Markdown ─────────────────────────────────────
    markdown = _build_markdown(draft_report, brief)

    logger.info(
        "[draft_node] drafted %d sections from %d papers",
        len(draft_report.sections),
        len(paper_cards),
    )
    return {
        "draft_report": draft_report,
        "draft_markdown": markdown,
        # 关键：传递 paper_cards 到 state，供后续 verify_claims 使用
        "paper_cards": paper_cards,
    }


# ─── internal helpers ────────────────────────────────────────────────────────────


def _build_draft_report(cards: list[Any], brief: Any | None) -> DraftReport:
    """用 LLM 综合 PaperCards 生成结构化 DraftReport。"""
    from src.agent.llm import build_reason_llm
    from src.agent.settings import get_settings
    from langchain_core.messages import HumanMessage, SystemMessage

    brief_ctx = _build_brief_context(brief)
    # 传给 LLM 最多 20 张卡片（每张 ~1500 chars abstract ≈ ~750 tokens，20 张 ≈ 15k tokens）
    # 加上 system prompt (~2k tokens) + brief ctx (~500 tokens) + output (~8k tokens) = ~26k tokens，在 context 窗口内
    cards_text = _render_cards(cards[:20])

    SYSTEM = (
        'You are an expert academic survey writer. Generate a comprehensive, detailed survey report '
        "based on the provided paper cards. The output MUST be strictly valid JSON (no markdown code blocks).\n\n"
        "IMPORTANT RULES:\n"
        "1. EVERY section must contain substantive, specific content derived from the paper cards.\n"
        "   NEVER write '（待补充）' or 'to be added' or 'TBD' or 'placeholder'.\n"
        "   If a paper abstract mentions a method, dataset, benchmark, or finding — write it explicitly.\n"
        "2. For the 'methods' section: For EACH paper, infer the method from its abstract and describe:\n"
        "   - What the method does (concisely)\n"
        "   - Key innovation or insight\n"
        "   - Reference the paper with its citation label [N]\n"
        "3. For the 'datasets' section: List all mentioned benchmarks/datasets with their characteristics.\n"
        "4. For the 'taxonomy' section: Organize papers into categories with specific categorization criteria.\n"
        "5. For the 'evaluation' section: Include any numbers/metrics mentioned in abstracts when available.\n"
        '  "sections": {\n'
        '    "title": "Survey paper title — 15-25 Chinese characters, descriptive and specific",\n'
        '    "abstract": "Executive summary (400-600 chars) — motivation, scope, key findings, contributions",\n'
        '    "introduction": "Comprehensive introduction (800-1200 chars) — research context, evolution of the field, '
        'motivation for this survey, main contributions, paper organization roadmap",\n'
        '    "background": "Background & motivation (600-1000 chars) — foundational concepts, '
        'problem formalization, historical context, why this field matters, key challenges driving research",\n'
        '    "taxonomy": "Detailed taxonomy & categorization (1000-1500 chars) — hierarchical organization '
        'of methods/approaches. For EACH category: category name, key characteristics, representative papers. '
        'Use citation labels like [1], [2], etc. for each paper referenced.",\n'
        '    "methods": "Core methods deep-dive (1200-1800 chars) — For EACH paper: method name, what it does, '
        'key technical innovations, strengths and weaknesses. Cross-reference with citation labels. '
        'Infer methods from abstract when methods field is absent in cards.",\n'
        '    "datasets": "Datasets & experimental settings (600-1000 chars) — benchmark datasets, '
        'evaluation metrics, experimental protocols. Table format preferred when possible: '
        '| Dataset | Type | Size | Notes |. '
        'Infer datasets from abstract when datasets field is absent in cards.",\n'
        '    "evaluation": "Performance comparison & analysis (800-1200 chars) — quantitative comparison '
        'across methods on key benchmarks. Include specific numbers from abstracts when available. '
        'Identify best-performing methods per metric.",\n'
        '    "discussion": "Discussion & insights (600-900 chars) — cross-cutting themes, trade-offs '
        'between approaches, reproducibility issues, common pitfalls, lessons learned. '
        'Infer limitations from abstract when limitations field is absent in cards.",\n'
        '    "future_work": "Open challenges & future directions (500-800 chars) — unsolved problems, '
        'promising research avenues, potential breakthroughs, underexplored directions",\n'
        '    "conclusion": "Conclusion (300-500 chars) — summary of main findings, contributions, '
        'take-away messages for readers"\n'
        "  },\n"
        '  "claims": [\n'
        '    {"id": "c1", "text": "specific verifiable claim", "citation_labels": ["[1]", "[2]"]},\n'
        '    ...\n'
        "  ],\n"
        '  "citations": [\n'
        '    {"label": "[1]", "url": "https://arxiv.org/abs/...", "reason": "brief reason this paper is cited", "arxiv_id": "2301.01234"},\n'
        '    ...\n'
        "  ]\n"
        "}"
    )

    USER = (
        "{brief_ctx}"
        "\n\n## 论文卡片\n{cards_text}\n\n"
        "请根据以上论文卡片生成详尽的综述草稿。\n"
        "IMPORTANT: 必须从每张卡片的摘要(abstract)中提取并推断方法、数据集和关键技术贡献。\n"
        "不要留任何（待补充）占位文字。每个部分都要写实质内容。"
    ).format(brief_ctx=brief_ctx, cards_text=cards_text)

    try:
        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=8192, timeout_s=240)
        resp = llm.invoke([SystemMessage(content=SYSTEM), HumanMessage(content=USER)])
        text = getattr(resp, "content", "") or ""

        import json as _json
        raw = _extract_json(text)
        if raw:
            data = _json.loads(raw)
            sections = data.get("sections", {})
            claims = [Claim(**c) for c in data.get("claims", []) if c.get("id") and c.get("text")]
            citations = [Citation(**c) for c in data.get("citations", []) if c.get("label") and c.get("url")]

            # ── 关键修复：用 paper_cards 内容填充 citation.fetched_content ──
            citations = _inject_citation_content(citations, cards)

            return DraftReport(
                sections=sections,
                claims=claims,
                citations=citations,
            )
    except Exception as exc:
        logger.warning("[draft_node] LLM failed: %s, using template fallback", exc)

    # Fallback：基于 cards 构造基础 sections
    draft = _fallback_draft(cards, brief)
    # Fallback 也要注入 content
    draft.citations = _inject_citation_content(draft.citations, cards)
    return draft


def _build_markdown(draft: DraftReport, brief: Any | None) -> str:
    """将 DraftReport 渲染为可读 Markdown。"""
    lines: list[str] = []

    topic = ""
    if brief:
        topic = (brief.get("topic") if isinstance(brief, dict) else getattr(brief, "topic", "")) or ""

    # Title (may come from sections.title or topic)
    title = draft.sections.get("title") or topic
    lines.append(f"# {title}")
    lines.append("")

    # Abstract
    if "abstract" in draft.sections:
        lines.append("## Abstract")
        lines.append("")
        lines.append(draft.sections["abstract"])
        lines.append("")

    # Main sections in canonical order
    section_order = [
        "introduction",
        "background",
        "taxonomy",
        "methods",
        "datasets",
        "evaluation",
        "discussion",
        "future_work",
        "conclusion",
    ]

    for sec_key in section_order:
        if sec_key in draft.sections and sec_key not in ("title", "abstract"):
            lines.append(f"## {sec_key.replace('_', ' ').title()}")
            lines.append("")
            lines.append(draft.sections[sec_key])
            lines.append("")

    # Any remaining sections not in the canonical order
    for sec_name, sec_body in draft.sections.items():
        if sec_name not in section_order and sec_name not in ("title", "abstract"):
            display_name = sec_name.replace("_", " ").title()
            lines.append(f"## {display_name}")
            lines.append("")
            lines.append(sec_body)
            lines.append("")

    # References
    if draft.citations:
        lines.append("## References")
        lines.append("")
        for c in draft.citations:
            reason = c.reason or ""
            lines.append(f"- {c.label} {reason}: {c.url}")

    return "\n".join(lines)


def _fallback_draft(cards: list[Any], brief: Any | None) -> DraftReport:
    """
    当 LLM 综合失败时，基于 cards 构造 DraftReport。

    策略：不用模板占位，而是从每张 card 的 abstract 中提取并重组内容，
    生成与卡片内容严格对应的结构化报告。
    """
    sections: dict[str, str] = {}

    topic = ""
    sub_questions = []
    if brief:
        topic = (brief.get("topic") if isinstance(brief, dict) else getattr(brief, "topic", "")) or ""
        sq = brief.get("sub_questions") if isinstance(brief, dict) else getattr(brief, "sub_questions", [])
        sub_questions = sq if isinstance(sq, list) else []

    # ── 1. 收集所有卡片数据 ──────────────────────────────────────────
    all_abstracts: list[dict] = []
    all_methods: list[dict] = []  # {paper_idx, method}
    all_datasets: list[dict] = []  # {paper_idx, dataset}
    all_limitations: list[dict] = []

    for i, card in enumerate(cards[:20]):
        abstract = _get_field(card, "abstract", "") or _get_field(card, "summary", "")
        title = _get_field(card, "title", f"Paper {i+1}")
        arxiv_id = _get_field(card, "arxiv_id", "")
        authors = _get_field(card, "authors", [])
        authors_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "") if authors else "Unknown"

        card_meta = {
            "idx": i + 1,
            "label": f"[{i+1}]",
            "title": title,
            "authors": authors_str,
            "arxiv_id": arxiv_id,
            "abstract": abstract,
        }

        if abstract and len(abstract) > 30:
            all_abstracts.append(card_meta)

        # 收集方法
        methods = _get_field(card, "methods", [])
        if isinstance(methods, list):
            for m in methods:
                all_methods.append({**card_meta, "method": str(m)})

        # 收集数据集
        datasets = _get_field(card, "datasets", [])
        if isinstance(datasets, list):
            for d in datasets:
                all_datasets.append({**card_meta, "dataset": str(d)})

        # 收集局限性
        limitations = _get_field(card, "limitations", [])
        if isinstance(limitations, list):
            for l in limitations:
                all_limitations.append({**card_meta, "limitation": str(l)})

    # ── 2. Abstract ─────────────────────────────────────────────────
    if all_abstracts:
        abstract_snippets = "；".join(
            f"{c['title']}（{c['authors']}）：{c['abstract'][:200]}"
            for c in all_abstracts[:5]
        )
        sections["abstract"] = (
            f"本综述围绕「{topic or '该研究领域'}」展开，涵盖 {len(all_abstracts)} 篇相关论文。"
            f"主要研究包括：{abstract_snippets}。"
        )

    # ── 3. Introduction ────────────────────────────────────────────
    intro_parts = [f"本综述围绕「{topic or '该研究领域'}」，共分析了 {len(all_abstracts)} 篇相关论文。"]
    if sub_questions:
        intro_parts.append(f"本综述旨在回答以下核心问题：{'；'.join(sub_questions[:3])}。")
    if all_abstracts:
        intro_parts.append(f"代表性工作涵盖：{'、'.join(c['title'] for c in all_abstracts[:3])}等。")
    sections["introduction"] = "".join(intro_parts)

    # ── 4. Background ───────────────────────────────────────────────
    if all_abstracts:
        bg_parts = ["## 相关研究背景\n\n"]
        for c in all_abstracts[:5]:
            bg_parts.append(
                f"**{c['label']} {c['title']}**（{c['authors']}）\n"
                f"{c['abstract'][:400]}\n\n"
            )
        sections["background"] = "".join(bg_parts)

    # ── 5. Taxonomy（从论文中归纳分类）─────────────────────────────────
    if all_abstracts:
        taxonomy_parts = [
            f"基于对 {len(all_abstracts)} 篇论文的分析，该领域可从以下维度分类：\n\n"
        ]
        # 简单按 arxiv_id 是否含 swe-agent/swe-bench 相关关键词分
        swe_cards = [c for c in all_abstracts if "swe" in c["title"].lower()]
        agent_cards = [c for c in all_abstracts if c not in swe_cards and ("agent" in c["title"].lower() or "benchmark" in c["title"].lower())]
        other_cards = [c for c in all_abstracts if c not in swe_cards and c not in agent_cards]

        if swe_cards:
            taxonomy_parts.append("**分类一：基准评测类（SWE-bench 系列）**\n")
            for c in swe_cards[:5]:
                taxonomy_parts.append(f"- {c['label']} {c['title']} — {c['authors']}\n")
            taxonomy_parts.append("\n")

        if agent_cards:
            taxonomy_parts.append("**分类二：Agent 方法类**\n")
            for c in agent_cards[:5]:
                taxonomy_parts.append(f"- {c['label']} {c['title']} — {c['authors']}\n")
            taxonomy_parts.append("\n")

        if other_cards:
            taxonomy_parts.append("**分类三：其他相关工作**\n")
            for c in other_cards[:5]:
                taxonomy_parts.append(f"- {c['label']} {c['title']} — {c['authors']}\n")
            taxonomy_parts.append("\n")

        sections["taxonomy"] = "".join(taxonomy_parts)

    # ── 6. Methods ─────────────────────────────────────────────────
    if all_methods:
        method_parts = ["本综述涉及的主要方法包括：\n\n"]
        # 按方法名分组
        method_map: dict[str, list] = {}
        for m_info in all_methods:
            key = m_info["method"]
            if key not in method_map:
                method_map[key] = []
            method_map[key].append(m_info)

        for method, occurrences in method_map.items():
            papers = ", ".join(f"{occ['label']}" for occ in occurrences[:3])
            method_parts.append(f"- **{method}**：出现在 {len(occurrences)} 篇论文中（{papers}）\n")
        sections["methods"] = "".join(method_parts)
    elif all_abstracts:
        # 从 abstract 推断方法
        method_parts = ["从论文摘要中归纳的主要方法：\n\n"]
        for c in all_abstracts[:8]:
            method_parts.append(
                f"- **{c['label']} {c['title']}**："
                f"{c['abstract'][:300]}...\n\n"
            )
        sections["methods"] = "".join(method_parts)

    # ── 7. Datasets ────────────────────────────────────────────────
    if all_datasets:
        dataset_parts = ["涉及的主要数据集和基准：\n\n"]
        dataset_parts.append("| 数据集/基准 | 涉及论文 | 说明 |\n")
        dataset_parts.append("|---|---|---|\n")
        dataset_map: dict[str, list] = {}
        for d_info in all_datasets:
            key = d_info["dataset"]
            if key not in dataset_map:
                dataset_map[key] = []
            dataset_map[key].append(d_info)
        for dataset, occurrences in dataset_map.items():
            papers = ", ".join(occ["label"] for occ in occurrences[:5])
            dataset_parts.append(f"| {dataset} | {papers} | |\n")
        sections["datasets"] = "".join(dataset_parts)
    elif all_abstracts:
        sections["datasets"] = (
            "从论文摘要中可发现的数据集："
            + "、".join(c.get("title", "") for c in all_abstracts[:6])
            + "等。具体数据集信息见各论文。"
        )

    # ── 8. Evaluation ───────────────────────────────────────────
    if all_abstracts:
        eval_parts = ["各论文的主要实验结果和评测信息：\n\n"]
        for c in all_abstracts[:8]:
            eval_parts.append(
                f"**{c['label']} {c['title']}**："
                f"{c['abstract'][:400]}...\n\n"
            )
        sections["evaluation"] = "".join(eval_parts)

    # ── 9. Discussion ──────────────────────────────────────────────
    if all_limitations:
        disc_parts = ["各论文提到的主要局限性：\n\n"]
        for l_info in all_limitations[:10]:
            disc_parts.append(
                f"- **{l_info['label']} {l_info['title']}**：{l_info['limitation']}\n"
            )
        sections["discussion"] = "".join(disc_parts)
    elif all_abstracts:
        sections["discussion"] = (
            "本综述涉及的论文在方法上各有创新，"
            + "、".join(c["title"] for c in all_abstracts[:3])
            + "等是代表性工作。详细讨论见各论文。"
        )

    # ── 10. Future Work ─────────────────────────────────────────
    if all_limitations:
        fw_parts = ["基于现有工作的局限性，未来研究方向可包括：\n"]
        seen = set()
        for l_info in all_limitations[:5]:
            lim = l_info["limitation"]
            if lim not in seen:
                seen.add(lim)
                fw_parts.append(f"- {lim} → 需要进一步研究\n")
        sections["future_work"] = "".join(fw_parts)
    else:
        sections["future_work"] = (
            "根据现有论文分析，该方向的主要局限包括："
            "当前方法在泛化性和效率上仍有提升空间；"
            "多数工作在特定场景下表现较好，跨领域适用性有待验证；"
            "评估基准和指标尚不统一。"
        )

    # ── 11. Conclusion ──────────────────────────────────────────
    sections["conclusion"] = (
        f"本综述围绕「{topic or '该研究领域'}」，综合分析了 {len(all_abstracts)} 篇相关论文。"
        "主要贡献在于系统梳理了该领域的技术发展脉络，识别了核心方法与数据集，"
        "并指出了当前局限与未来研究方向。"
    )

    # ── 12. Citations ─────────────────────────────────────────────
    citations: list[Citation] = []
    claims: list[Claim] = []
    for i, card in enumerate(cards[:20]):
        label = f"[{i+1}]"
        title = _get_field(card, "title", f"Paper {i+1}")
        arxiv_id = _get_field(card, "arxiv_id", "")
        url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else _get_field(card, "url", "")
        title_str = title if isinstance(title, str) and title else "Unknown"
        full_abstract = _get_field(card, "abstract", "") or _get_field(card, "summary", "")
        citations.append(Citation(
            label=label,
            url=url,
            reason=title_str,
            fetched_content=full_abstract[:1000] if full_abstract else "",
        ))
        claim_text = full_abstract[:300] if full_abstract else f"{title_str} 是该领域的重要工作"
        claims.append(Claim(
            id=f"c{i+1}",
            text=claim_text,
            citation_labels=[label],
        ))

    return DraftReport(sections=sections, claims=claims, citations=citations)


def _get_field(obj: Any, key: str, default: str = "") -> Any:
    """
    安全获取字段。None 值被视为缺失，返回默认值。
    """
    if isinstance(obj, dict):
        val = obj.get(key, default)
        return val if val is not None else default
    val = getattr(obj, key, default)
    return val if val is not None else default


def _extract_arxiv_id_from_url(url: str) -> str | None:
    """从 URL 中提取 arXiv ID。"""
    import re
    patterns = [
        r"arxiv\.org/abs/(\d+\.\d+)",
        r"arxiv\.org/pdf/(\d+\.\d+)",
        r"arxiv\.org/(\d+\.\d+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def _inject_citation_content(citations: list[Citation], cards: list[Any]) -> list[Citation]:
    """
    关键修复：用 paper_cards 的内容填充 citation.fetched_content。

    问题：draft 生成的 citations 只有 url/reason，没有 paper 内容，
    导致 resolve_citations 无法获取足够 evidence 来验证 claim。

    解决：直接用对应 paper_card 的 abstract/summary 作为 fetched_content。
    """
    updated: list[Citation] = []

    for cit in citations:
        # 尝试匹配 paper_card
        matched_content: str | None = None
        cit_arxiv_id = _extract_arxiv_id_from_url(cit.url) if cit.url else None

        for card in cards:
            card_arxiv_id = _get_field(card, "arxiv_id", "")
            card_url = _get_field(card, "url", "")
            card_title = _get_field(card, "title", "")

            # 匹配逻辑：arxiv_id 或 url 匹配
            matched = False
            if cit_arxiv_id and card_arxiv_id and cit_arxiv_id == card_arxiv_id:
                matched = True
            elif card_url and cit.url and card_url == cit.url:
                matched = True
            elif card_title and cit.reason and card_title.lower() in cit.reason.lower():
                matched = True

            if matched:
                # 优先使用 abstract，其次 summary
                content = (
                    _get_field(card, "abstract", "") or
                    _get_field(card, "summary", "") or
                    _get_field(card, "content", "")
                )
                if content and len(content) > 50:
                    matched_content = content
                    break

        if matched_content:
            updated.append(cit.model_copy(update={"fetched_content": matched_content}))
        else:
            updated.append(cit)

    logger.debug(
        "[draft_node] injected content into %d/%d citations",
        sum(1 for c in updated if getattr(c, "fetched_content", None)),
        len(updated),
    )
    return updated


def _build_brief_context(brief: Any | None) -> str:
    if not brief:
        return ""
    topic = (brief.get("topic") if isinstance(brief, dict) else getattr(brief, "topic", "")) or ""
    sub_questions = (brief.get("sub_questions") if isinstance(brief, dict) else getattr(brief, "sub_questions", [])) or []
    desired = (brief.get("desired_output") if isinstance(brief, dict) else getattr(brief, "desired_output", "")) or "survey"
    ctx = f"## 研究主题\n{topic}\n\n"
    if sub_questions:
        ctx += "## 子问题\n" + "\n".join(f"- {q}" for q in sub_questions) + "\n\n"
    ctx += f"## 期望输出\n{desired}\n\n"
    return ctx


def _render_cards(cards: list[Any]) -> str:
    """将 PaperCards 渲染为供 LLM 消费的文本（包含完整摘要 + 所有结构化字段）。"""
    parts = []
    for i, card in enumerate(cards):
        title = _get_field(card, "title", "Untitled")
        authors = _get_field(card, "authors", [])
        if isinstance(authors, list):
            authors_str = ", ".join(authors[:5]) + ("..." if len(authors) > 5 else "")
        else:
            authors_str = str(authors)
        # 优先用完整 abstract，fallback 到 summary
        full_abstract = _get_field(card, "abstract", "") or _get_field(card, "summary", "")
        methods = _get_field(card, "methods", [])
        datasets = _get_field(card, "datasets", [])
        limitations = _get_field(card, "limitations", [])
        keywords = _get_field(card, "keywords", [])
        arxiv_id = _get_field(card, "arxiv_id", "")
        url = _get_field(card, "url", "")
        year = _get_field(card, "published_year", "")
        venue = _get_field(card, "venue", "")

        part = f"=== 论文 {i+1} ===\n"
        part += f"标题：{title}\n"
        part += f"作者：{authors_str or '未知'}\n"
        if year:
            part += f"年份：{year}\n"
        if venue:
            part += f"会议/期刊：{venue}\n"
        part += f"arXiv ID：{arxiv_id or '无'}\n"
        part += f"链接：{url or '无'}\n"
        if methods:
            part += f"方法：{', '.join(methods[:8])}\n"
        if datasets:
            part += f"数据集/基准：{', '.join(datasets[:8])}\n"
        if limitations:
            part += f"局限性：{', '.join(limitations[:5])}\n"
        if keywords:
            part += f"关键词：{', '.join(keywords[:10])}\n"
        # 传给 LLM 的摘要不要截断，让 LLM 自己决定消费方式
        part += f"摘要（完整）：\n{full_abstract}\n"
        parts.append(part)
    return "\n\n".join(parts)


def _extract_json(text: str) -> str | None:
    """
    从 LLM 输出中提取 JSON（支持数组 [ ] 和对象 { }）。
    """
    import json, re
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    for start_char, end_char in [("[", "]"), ("{", "}")]:
        idx_start = text.find(start_char)
        idx_end = text.rfind(end_char)
        if idx_start != -1 and idx_end != -1 and idx_end > idx_start:
            try:
                json.loads(text[idx_start:idx_end + 1])
                return text[idx_start:idx_end + 1]
            except json.JSONDecodeError:
                pass

    if text and text[0] in '{"[':
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass
    return None

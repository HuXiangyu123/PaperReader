"""Extract node — Phase 2: 从 RagResult.paper_candidates 抽取 PaperCards。

Progressive Reading 策略（参考 DeepXiv）：
1. DeepXiv brief（优先）：每篇论文先尝试 get_paper_brief，获取 TLDR + keywords + GitHub URL
2. LLM 抽取（次级）：brief 失败时，用 LLM 批量抽取 structured 信息
3. Fallback（兜底）：都失败时，用 _simple_card 保留原始 abstract

每张 PaperCard 包含：
- title, authors, arxiv_id, url
- summary（DeepXiv brief.tldr 或 LLM 摘要）
- keywords（DeepXiv brief.keywords 或规则提取）
- methods, datasets, limitations
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from src.tasking.trace_wrapper import get_trace_store, trace_node

logger = logging.getLogger(__name__)

# extract_node 处理论文数量上限（每篇 ~30s LLM 调用，30篇约 5min）
MAX_EXTRACT_CANDIDATES = 30


@trace_node(node_name="extract", stage="search", store=get_trace_store())
def extract_node(state: dict) -> dict:
    """
    Phase 2 抽取节点。

    输入：state.rag_result.paper_candidates, state.brief
    输出：state.paper_cards（list[dict]）
    """
    rag_result = state.get("rag_result")
    brief = state.get("brief")

    # 兼容 dict 和 RagResult 对象
    if isinstance(rag_result, dict):
        candidates = rag_result.get("paper_candidates", [])
    elif hasattr(rag_result, "paper_candidates"):
        candidates = rag_result.paper_candidates
    else:
        candidates = []

    if not candidates:
        return {"paper_cards": []}

    # 候选数量过多时截断（按相关度排序后取前 N 篇）
    # 注意：deepxiv brief fetch 也在本函数内部，须在收集 arxiv_ids 之前截断
    total = len(candidates)
    if total > MAX_EXTRACT_CANDIDATES:
        logger.info("[extract_node] truncating %d candidates to %d", total, MAX_EXTRACT_CANDIDATES)
        candidates = candidates[:MAX_EXTRACT_CANDIDATES]

    # 批量 LLM 抽取（并行）
    cards = _extract_cards_batch(candidates, brief)
    logger.info("[extract_node] extracted %d paper cards", len(cards))
    return {"paper_cards": cards}


def _extract_cards_batch(candidates: list[Any], brief: Any | None) -> list[dict]:
    """
    Progressive Reading 策略（参考 DeepXiv）：

    1. DeepXiv brief（优先）：所有有 arxiv_id 的论文并行获取 TLDR + keywords + github
    2. LLM 抽取（次级）：用 LLM 批量抽取 structured 信息
    3. Fallback（兜底）：都失败时用 _simple_card

    每批 3 篇并行 LLM 抽取，避免 token 超限。
    """
    from src.agent.llm import build_reason_llm
    from src.agent.settings import get_settings
    from langchain_core.messages import HumanMessage, SystemMessage
    from src.tools.deepxiv_client import get_paper_brief

    settings = get_settings()
    brief_ctx = _build_brief_context(brief)

    # ── Step 1：DeepXiv brief（Progressive reading 第一步）─────────────────
    brief_map: dict[str, dict] = {}
    arxiv_ids_for_brief: list[str] = []
    for cand in candidates:
        aid = None
        if isinstance(cand, dict):
            aid = cand.get("arxiv_id") or ""
        else:
            aid = getattr(cand, "arxiv_id", "") or ""
        if aid and len(aid) >= 6:
            arxiv_ids_for_brief.append(aid)

    if arxiv_ids_for_brief:
        logger.info("[extract_node] fetching DeepXiv briefs for %d papers", len(arxiv_ids_for_brief))
        try:
            from src.tools.deepxiv_client import batch_get_briefs
            brief_map = batch_get_briefs(arxiv_ids_for_brief, max_workers=4, delay_per_request=0.3)
        except Exception as e:
            logger.warning("[extract_node] DeepXiv brief batch failed: %s", e)

    # ── Step 2：LLM 批量抽取（每批 3 篇）─────────────────────────────────
    SYSTEM_PROMPT = (
        "你是一个论文结构化信息抽取专家。根据以下论文元数据，生成结构化的 PaperCard。\n"
        "【重要】必须保留原始元数据：若原文中提供了 title/authors/arxiv_id/url，必须复制到输出中，"
        "不要留空或置 null。\n"
        "输出严格 JSON（不带 markdown 代码块），字段说明：\n"
        "{\n"
        '  "title": "论文标题（必须，非空）",\n'
        '  "authors": ["作者1", "作者2"]（必须，若未知则从摘要中推断或写"Unknown"）\n'
        '  "published_year": 2024,\n'
        '  "venue": "会议/期刊名称",\n'
        '  "arxiv_id": "2412.00001",\n'
        '  "url": "https://...",\n'
        '  "summary": "300字以内的摘要概括",\n'
        '  "keywords": ["关键词1", "关键词2"],\n'
        '  "methods": ["方法1", "方法2"],\n'
        '  "datasets": ["数据集1"],\n'
        '  "limitations": ["局限性1"]\n'
        "}\n"
        "【强制】title 和 authors 必须非空。严格 JSON，不要有额外文字。"
    )

    USER_PROMPT = (
        "{brief_ctx}"
        "\n\n## 待抽取的论文\n"
        "{paper_text}"
    )

    # 批量打包：每批 3 篇，减少 token 数量（避免超时）
    BATCH_SIZE = 3
    all_cards: list[dict] = []

    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i : i + BATCH_SIZE]
        paper_texts = []
        for idx, cand in enumerate(batch):
            if isinstance(cand, dict):
                title = cand.get("title", "Unknown")
                abstract = cand.get("abstract", "")
                authors = cand.get("authors", [])
                arxiv_id = cand.get("arxiv_id", "")
                url = cand.get("url", "")
            else:
                title = getattr(cand, "title", "Unknown")
                abstract = getattr(cand, "abstract", "")
                authors = getattr(cand, "authors", [])
                arxiv_id = getattr(cand, "arxiv_id", "")
                url = getattr(cand, "url", "")

            # DeepXiv brief 优先用 TLDR 替换 abstract
            deepxiv_brief = brief_map.get(arxiv_id)
            display_abstract = abstract
            if deepxiv_brief:
                tldr = deepxiv_brief.get("tldr", "") or deepxiv_brief.get("abstract", "")
                if tldr:
                    display_abstract = tldr

            paper_texts.append(
                f"=== 论文 {i + idx + 1} ===\n"
                f"标题：{title}\n"
                f"作者：{', '.join(authors) if authors else '未知'}\n"
                f"arXiv ID：{arxiv_id or '无'}\n"
                f"链接：{url or '无'}\n"
                f"摘要：{display_abstract[:1500]}"
            )

        user_content = USER_PROMPT.format(
            brief_ctx=brief_ctx,
            paper_text="\n\n".join(paper_texts),
        )

        try:
            llm = build_reason_llm(settings, max_tokens=2048, timeout_s=180)
            resp = llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ])
            text = getattr(resp, "content", "") or ""
            import json as _json
            raw = _extract_json(text)
            if raw:
                data = _json.loads(raw)
                if isinstance(data, list):
                    cards = data
                elif isinstance(data, dict):
                    cards = [data]
                else:
                    cards = []
                for card_idx, card in enumerate(cards):
                    card["card_id"] = f"card_{len(all_cards)}"
                    orig_idx = i + card_idx
                    if 0 <= orig_idx < len(candidates):
                        _enrich_card(card, candidates[orig_idx])
                        # DeepXiv brief 信息补充
                        aid = card.get("arxiv_id") or candidates[orig_idx].get("arxiv_id") if isinstance(candidates[orig_idx], dict) else getattr(candidates[orig_idx], "arxiv_id", "") or ""
                        if aid and aid in brief_map:
                            _merge_deepxiv_brief(card, brief_map[aid])
                    else:
                        _enrich_card(card)
                    all_cards.append(card)
            else:
                # LLM 失败：直接用 DeepXiv brief 或 raw candidate
                for batch_idx2, cand_item2 in enumerate(batch):
                    aid = cand_item2.get("arxiv_id") if isinstance(cand_item2, dict) else getattr(cand_item2, "arxiv_id", "") or ""
                    if aid and aid in brief_map:
                        card = _card_from_deepxiv_brief(brief_map[aid], f"card_{len(all_cards)}")
                        _enrich_card(card, cand_item2)
                        all_cards.append(card)
                    else:
                        all_cards.append(_simple_card(cand_item2, len(all_cards)))
        except Exception as exc:
            logger.warning("LLM extract failed for batch %d: %s", i // BATCH_SIZE, exc)
            # Fallback: DeepXiv brief 优先
            for cand_item2 in batch:
                aid = cand_item2.get("arxiv_id") if isinstance(cand_item2, dict) else getattr(cand_item2, "arxiv_id", "") or ""
                if aid and aid in brief_map:
                    card = _card_from_deepxiv_brief(brief_map[aid], f"card_{len(all_cards)}")
                    _enrich_card(card, cand_item2)
                    all_cards.append(card)
                else:
                    all_cards.append(_simple_card(cand_item2, len(all_cards)))

    return all_cards


def _merge_deepxiv_brief(card: dict, brief: dict) -> None:
    """将 DeepXiv brief 信息合并到 card 中（不覆盖已有字段）。"""
    if not brief:
        return
    # keywords：补充到已有的 keywords 列表
    if brief.get("keywords"):
        existing = card.get("keywords", [])
        if isinstance(existing, list) and existing:
            combined = list(dict.fromkeys([*existing, *[str(k) for k in brief["keywords"]]]))
            card["keywords"] = combined[:10]
        else:
            card["keywords"] = [str(k) for k in brief["keywords"][:10]]
    # github_url
    if brief.get("github_url") and not card.get("github_url"):
        card["github_url"] = brief["github_url"]
    # tldr：如果 summary 为空，用 tldr 填充
    tldr = brief.get("tldr", "")
    if tldr and not card.get("summary"):
        card["summary"] = tldr[:300]
        if not card.get("abstract"):
            card["abstract"] = tldr


def _card_from_deepxiv_brief(brief: dict, card_id: str) -> dict:
    """从 DeepXiv brief 构造 PaperCard（DeepXiv 失败时用）。"""
    return {
        "card_id": card_id,
        "title": brief.get("title", "Unknown"),
        "arxiv_id": brief.get("arxiv_id", ""),
        "url": brief.get("url", ""),
        "summary": brief.get("tldr", "") or "",
        "keywords": [str(k) for k in (brief.get("keywords") or [])],
        "github_url": brief.get("github_url") or "",
        "authors": brief.get("authors", []),
        "abstract": brief.get("tldr", "") or "",
        "methods": [],
        "datasets": [],
        "limitations": [],
        "citations": [],
    }


def _extract_json(text: str) -> str | None:
    """
    从 LLM 输出中提取 JSON（支持数组 [ ] 和对象 { }）。
    
    Robust 策略：
    1. 去掉 markdown 代码块
    2. 找第一个 [ 或 { 到最后一个 ] 或 } 
    3. 用 json.loads 验证合法性
    """
    import json
    text = text.strip()
    # 去掉 markdown 代码块
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # 尝试找数组格式 [ ... ]
    arr_start = text.find("[")
    arr_end = text.rfind("]")
    if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
        try:
            json.loads(text[arr_start:arr_end + 1])
            return text[arr_start:arr_end + 1]
        except json.JSONDecodeError:
            pass  # 继续尝试对象格式

    # 尝试找对象格式 { ... }
    obj_start = text.find("{")
    obj_end = text.rfind("}")
    if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
        try:
            json.loads(text[obj_start:obj_end + 1])
            return text[obj_start:obj_end + 1]
        except json.JSONDecodeError:
            pass

    # 最后：直接从开头尝试完整 JSON 解析
    for start_char in ["{", "["]:
        if text.startswith(start_char):
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError:
                pass
    return None


def _build_brief_context(brief: Any | None) -> str:
    if not brief:
        return ""
    topic = (brief.get("topic") if isinstance(brief, dict) else getattr(brief, "topic", "")) or ""
    sub_questions = (brief.get("sub_questions") if isinstance(brief, dict) else getattr(brief, "sub_questions", [])) or []
    desired = (brief.get("desired_output") if isinstance(brief, dict) else getattr(brief, "desired_output", "")) or ""
    ctx = f"## 研究主题\n{topic}\n"
    if sub_questions:
        ctx += "\n## 子问题\n" + "\n".join(f"- {q}" for q in sub_questions) + "\n"
    if desired:
        ctx += f"\n## 期望输出\n{desired}\n"
    return ctx


def _enrich_card(card: dict, original_cand: Any | None = None) -> None:
    """
    从 abstract 中补充 methods / datasets，并回填原始 candidate 的 authors/title。

    若 LLM 丢失了 authors，回填原始 metadata。
    """
    abstract = card.get("summary") or card.get("abstract", "")

    # 规则补充 methods / datasets（仅当未设置时）—— 扩大关键词范围
    if not card.get("methods") and abstract:
        methods = _extract_entities(abstract, [
            # Agent & SWE
            "swe-bench", "code generation", "agent", "multi-agent", "tool use",
            "llm-based agent", "autonomous agent", "software engineering agent",
            "repl", "command execution", "test-driven", "bug fix", "pr review",
            # Core methods
            "transformer", "attention", "reinforcement learning", "graph neural network",
            "diffusion", "language model", "retrieval", "neural network",
            "contrastive", "fine-tuning", "pre-training", "distillation",
            "chain-of-thought", "planning", "reasoning", "self-consistency", "reflection",
            "self-adaptive", "context pruning", "retrieval-augmented generation",
            "rag", "debate", "multi-agent debate", "ensemble", "verifier",
            "Monte Carlo Tree Search", "MCTS", "PBT", "program synthesis",
            "semantic search", "hybrid retrieval", "cross-encoder", "BM25",
            "context window", "long context", "memory mechanism",
            "experience replay", "curriculum learning", "self-supervised",
            "adversarial training", "data augmentation", "few-shot", "zero-shot",
            "coarse-to-fine", "iterative refinement", "beam search",
            "greedy decoding", "nucleus sampling", "temperature sampling",
        ])
        if methods:
            card["methods"] = methods

    if not card.get("datasets") and abstract:
        datasets = _extract_entities(abstract, [
            "SWE-bench", "SWE-bench Verified", "SWE-bench Lite",
            "HumanEval", "MBPP", "APPS", "DS-1000", "MMLU", "BEIR",
            "BigCodeBench", "EvalPlus", "CRUXEval", "NaturalCodeBench",
            "CodeAgentBench", "AgentBench", "BFCL", "API-Bank",
            "ImageNet", "COCO", "SQuAD", "GLUE", "MNLI", "PubMed", "Wiki",
        ])
        if datasets:
            card["datasets"] = datasets

    # 确保 abstract 字段被保留（供 grounding 使用）
    if not card.get("abstract") and abstract:
        card["abstract"] = abstract

    # 回填 authors（LLM 最容易丢失此字段）
    if original_cand:
        orig_authors = None
        if isinstance(original_cand, dict):
            orig_authors = original_cand.get("authors", [])
        else:
            orig_authors = getattr(original_cand, "authors", [])

        card_authors = card.get("authors", [])
        if (not card_authors or not any(card_authors)) and orig_authors:
            card["authors"] = orig_authors

        # 同时回填 url / arxiv_id
        if not card.get("url"):
            card["url"] = (
                original_cand.get("url") if isinstance(original_cand, dict)
                else getattr(original_cand, "url", "")
            )
        if not card.get("arxiv_id"):
            card["arxiv_id"] = (
                original_cand.get("arxiv_id") if isinstance(original_cand, dict)
                else getattr(original_cand, "arxiv_id", "")
            )


def _extract_entities(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def _simple_card(cand: Any, idx: int) -> dict:
    """从 raw candidate 构造一个最简 card（LLM 失败时 fallback）。

    关键：必须保留原始 abstract/summary 作为 summary 字段，
    因为它是后续 ground_draft_report 和 verify_claims 的主要 evidence 来源。
    """
    if isinstance(cand, dict):
        title = cand.get("title", "Untitled")
        authors = cand.get("authors", [])
        abstract = cand.get("abstract", "")
        arxiv_id = cand.get("arxiv_id")
        url = cand.get("url", "")
    else:
        title = getattr(cand, "title", "Untitled")
        authors = getattr(cand, "authors", [])
        abstract = getattr(cand, "abstract", "")
        arxiv_id = getattr(cand, "arxiv_id", None)
        url = getattr(cand, "url", "")

    # 提取 summary（保留较长摘要供 drafting 使用，1500 字符足够 LLM 推断内容）
    summary_text = (abstract or "")[:1500] + ("..." if len(abstract) > 1500 else "")

    # 规则化提取 methods / datasets（扩大关键词范围）
    methods = _extract_entities(abstract, [
        # Agent & SWE
        "swe-bench", "code generation", "agent", "multi-agent", "tool use",
        "llm-based agent", "autonomous agent", "software engineering agent",
        "repl", "command execution", "test-driven", "bug fix", "pr review",
        # Core methods
        "transformer", "attention", "reinforcement learning", "graph neural network",
        "diffusion", "language model", "retrieval", "neural network",
        "contrastive", "fine-tuning", "pre-training", "distillation",
        "chain-of-thought", "planning", "reasoning", "self-consistency", "reflection",
        "self-adaptive", "context pruning", "retrieval-augmented generation",
        "rag", "debate", "multi-agent debate", "ensemble", "verifier",
        "Monte Carlo Tree Search", "MCTS", "PBT", "program synthesis",
        "semantic search", "hybrid retrieval", "cross-encoder", "BM25",
        "context window", "long context", "memory mechanism",
        "experience replay", "curriculum learning", "self-supervised",
        "adversarial training", "data augmentation", "few-shot", "zero-shot",
    ])
    datasets = _extract_entities(abstract, [
        "SWE-bench", "SWE-bench Verified", "SWE-bench Lite",
        "HumanEval", "MBPP", "APPS", "DS-1000", "MMLU", "BEIR",
        "BigCodeBench", "EvalPlus", "CRUXEval", "NaturalCodeBench",
        "CodeAgentBench", "AgentBench", "BFCL", "API-Bank",
        "ImageNet", "COCO", "SQuAD", "GLUE", "MNLI", "PubMed", "Wiki",
    ])

    return {
        "card_id": f"card_{idx}",
        "title": title,
        "authors": authors if isinstance(authors, list) else [],
        "abstract": abstract,  # 保留完整 abstract（grounding 关键）
        "arxiv_id": arxiv_id,
        "url": url,
        "published_year": None,
        "venue": None,
        "summary": summary_text,
        "methods": methods,
        "datasets": datasets,
        "limitations": [],
        "citations": [],
    }

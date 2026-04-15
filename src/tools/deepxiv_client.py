"""DeepXiv Client — 封装 deepxiv_sdk.Reader，支持 search / brief / head / trending / section。

核心策略（参考 DeepXiv 设计）：
1. Search-first：先用关键词搜，judge 快速判断相关性
2. Progressive reading：brief（判断价值）→ head（看结构）→ section（读关键段落）→ raw（完整 PDF）
3. Trending discovery：按热度发现论文，不依赖关键词匹配
4. Semantic Scholar metadata：用 Semantic Scholar ID 获取更丰富的元信息

Token 管理：
- 自动注册匿名 token（1000 请求/天），存储在 ~/.env
- 如需更高限额，用户在 data.rag.ac.cn/register 注册
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── DeepXiv Reader 初始化 ────────────────────────────────────────────────────

_reader = None
_reader_init_ok = False
_reader_init_error: str | None = None


def _init_reader() -> Any:
    """延迟初始化 DeepXiv Reader（避免启动时强制要求 token）。"""
    global _reader, _reader_init_ok, _reader_init_error

    if _reader is not None:
        return _reader

    try:
        from deepxiv_sdk import Reader

        # 自动注册 token（首次调用时触发，写入 ~/.env）
        _reader = Reader(timeout=60, max_retries=3)
        _reader_init_ok = True
        logger.info("[DeepXiv] Reader initialized successfully")
        return _reader
    except Exception as e:
        _reader_init_error = str(e)
        logger.warning("[DeepXiv] Reader init failed: %s (will use fallback)", e)
        return None


def is_available() -> bool:
    """检查 DeepXiv 是否可用。"""
    if _reader is None:
        _init_reader()
    return _reader_init_ok


# ── Search API ─────────────────────────────────────────────────────────────

def search_papers(
    query: str,
    *,
    size: int = 10,
    date_from: str | None = None,
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    DeepXiv 关键词搜索 arXiv 论文。

    参数：
        query：搜索关键词
        size：返回数量（默认 10，最大 100）
        date_from：起始日期，如 "2024-01-01"
        categories：限定 cs.AI / cs.CL / cs.LG 等

    返回：
        [{arxiv_id, title, abstract, authors, published, categories, authors}, ...]
    """
    reader = _init_reader()
    if reader is None:
        return []

    try:
        results = reader.search(
            query,
            size=min(size, 100),
            categories=categories,
            min_date=date_from,
        )

        papers = []
        for item in (results or []):
            arxiv_id = str(item.get("arxiv_id", "") or item.get("id", ""))
            if arxiv_id:
                arxiv_id = arxiv_id.strip()
            papers.append({
                "arxiv_id": arxiv_id,
                "title": str(item.get("title", "") or "").strip(),
                "abstract": str(item.get("abstract", "") or "").strip(),
                "authors": item.get("authors", []),
                "published_date": str(item.get("published", "") or "")[:10],
                "categories": item.get("categories", []),
                "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else "",
                "_source": "deepxiv",
            })
        logger.info("[DeepXiv] search(%r) → %d papers", query, len(papers))
        return papers
    except Exception as e:
        logger.warning("[DeepXiv] search failed for %r: %s", query, e)
        return []


# ── Paper Brief API ─────────────────────────────────────────────────────────

def get_paper_brief(arxiv_id: str) -> dict[str, Any] | None:
    """
    获取单篇论文的 brief 信息（TLDR + keywords + GitHub URL）。

    DeepXiv brief 包含：
    - title, tldr, keywords, num_citations, numReferences, github_url

    比 raw abstract 更结构化，是 progressive reading 第一步。
    """
    reader = _init_reader()
    if reader is None:
        return None

    try:
        brief = reader.brief(arxiv_id)
        if not brief:
            return None

        result = {
            "arxiv_id": arxiv_id,
            "title": brief.get("title") or "",
            "tldr": brief.get("tldr") or brief.get("abstract") or "",
            "keywords": brief.get("keywords", []),
            "github_url": brief.get("github_url") or "",
            "num_citations": brief.get("num_citations") or 0,
            "num_references": brief.get("num_references") or 0,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        }
        logger.debug("[DeepXiv] brief(%s) → %s", arxiv_id, result.get("title", "")[:50])
        return result
    except Exception as e:
        logger.warning("[DeepXiv] brief failed for %s: %s", arxiv_id, e)
        return None


def get_paper_head(arxiv_id: str) -> dict[str, Any] | None:
    """
    获取论文结构和 token 分布（Progressive reading 第二步）。

    DeepXiv head 包含：
    - title, authors, sections（section_name → token_count）
    """
    reader = _init_reader()
    if reader is None:
        return None

    try:
        head = reader.head(arxiv_id)
        if not head:
            return None

        return {
            "arxiv_id": arxiv_id,
            "title": head.get("title") or "",
            "authors": head.get("authors", []),
            "sections": head.get("sections", {}),
            "total_tokens": head.get("total_tokens") or 0,
        }
    except Exception as e:
        logger.warning("[DeepXiv] head failed for %s: %s", arxiv_id, e)
        return None


def get_paper_section(arxiv_id: str, section: str) -> str | None:
    """
    读取论文特定章节（Progressive reading 第三步）。

    section 参数如 "Introduction", "Method", "Experiments", "Results", "Conclusion"
    """
    reader = _init_reader()
    if reader is None:
        return None

    try:
        text = reader.section(arxiv_id, section)
        return text if text else None
    except Exception as e:
        logger.warning("[DeepXiv] section(%s, %s) failed: %s", arxiv_id, section, e)
        return None


# ── Trending / Popularity API ─────────────────────────────────────────────

def get_trending_papers(
    days: int = 7,
    *,
    size: int = 30,
    categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    获取近期热门论文（按社交信号热度排序）。

    DeepXiv 策略：不依赖关键词匹配，按 trending 热度发现论文。
    用于 discovery 阶段，发现用户可能不知道的相关热文。
    """
    reader = _init_reader()
    if reader is None:
        return []

    try:
        results = reader.trending(days=days, size=min(size, 100))
        papers = []
        for item in (results or []):
            arxiv_id = str(item.get("arxiv_id", "") or item.get("id", "")).strip()
            papers.append({
                "arxiv_id": arxiv_id,
                "title": str(item.get("title", "") or "").strip(),
                "abstract": str(item.get("abstract", "") or "").strip(),
                "authors": item.get("authors", []),
                "published_date": str(item.get("published", "") or "")[:10],
                "categories": item.get("categories", []),
                "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else "",
                "_source": "deepxiv_trending",
            })
        logger.info("[DeepXiv] trending(days=%d) → %d papers", days, len(papers))
        return papers
    except Exception as e:
        logger.warning("[DeepXiv] trending failed: %s", e)
        return []


def get_paper_popularity(arxiv_id: str) -> dict[str, Any] | None:
    """获取论文的社交传播指标（views, tweets, likes, replies）。"""
    reader = _init_reader()
    if reader is None:
        return None

    try:
        pop = reader.popularity(arxiv_id)
        return pop if pop else None
    except Exception as e:
        logger.warning("[DeepXiv] popularity(%s) failed: %s", arxiv_id, e)
        return None


# ── Semantic Scholar Metadata ──────────────────────────────────────────────

def get_semantic_scholar(sc_id: str) -> dict[str, Any] | None:
    """通过 Semantic Scholar ID 获取丰富元信息（citations, references, fieldsOfStudy）。"""
    reader = _init_reader()
    if reader is None:
        return None

    try:
        meta = reader.semantic_scholar(sc_id)
        return meta if meta else None
    except Exception as e:
        logger.warning("[DeepXiv] semantic_scholar(%s) failed: %s", sc_id, e)
        return None


# ── Batch API ──────────────────────────────────────────────────────────────

def batch_get_briefs(
    arxiv_ids: list[str],
    *,
    max_workers: int = 4,
    delay_per_request: float = 0.5,
) -> dict[str, dict[str, Any]]:
    """
    批量获取 paper briefs（并行，带速率限制）。

    避免对 DeepXiv API 造成过大压力，每次请求间隔 delay_per_request 秒。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[str, dict[str, Any]] = {}

    def _fetch_one(aid: str) -> tuple[str, dict[str, Any] | None]:
        time.sleep(delay_per_request)
        return aid, get_paper_brief(aid)

    limited_ids = arxiv_ids[:50]  # 最多 50 个，避免 API 配额耗尽
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, aid): aid for aid in limited_ids}
        for future in as_completed(futures):
            try:
                aid, brief = future.result()
                if brief:
                    results[aid] = brief
            except Exception:
                pass

    logger.info("[DeepXiv] batch_briefs(%d) → %d fetched", len(arxiv_ids), len(results))
    return results

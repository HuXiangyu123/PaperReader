from __future__ import annotations

import re
import urllib.parse
import urllib.request
from html import unescape
from typing import Any

import feedparser


def _pick_pdf_url(entry: Any) -> str | None:
    for link in getattr(entry, "links", []):
        if getattr(link, "type", "") == "application/pdf" or getattr(link, "title", "") == "pdf":
            return getattr(link, "href", None)
    return None


def _parse_arxiv_feed(api_url: str, timeout_s: int = 6) -> Any:
    """Fetch arXiv API response with explicit timeout, then parse Atom."""
    request = urllib.request.Request(
        api_url,
        headers={"User-Agent": "PaperReaderAgent/1.0 (+https://arxiv.org)"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = response.read()
    return feedparser.parse(payload)


def _fetch_arxiv_abs_fallback(arxiv_id: str) -> dict[str, Any] | None:
    """Fallback metadata path when arXiv API is temporarily unavailable."""
    abs_url = f"https://arxiv.org/abs/{arxiv_id}"
    request = urllib.request.Request(
        abs_url,
        headers={
            "User-Agent": "PaperReaderAgent/1.0 (+https://arxiv.org)",
        },
    )
    with urllib.request.urlopen(request, timeout=6) as response:
        html = response.read().decode("utf-8", errors="ignore")

    # arXiv abstract pages expose metadata in OpenGraph tags.
    title_match = re.search(
        r'<meta\s+property="og:title"\s+content="([^"]+)"',
        html,
        flags=re.IGNORECASE,
    )
    desc_match = re.search(
        r'<meta\s+property="og:description"\s+content="([^"]+)"',
        html,
        flags=re.IGNORECASE,
    )
    if not title_match and not desc_match:
        return None

    title = unescape((title_match.group(1) if title_match else "").strip())
    abstract = unescape((desc_match.group(1) if desc_match else "").strip())
    abstract = re.sub(r"^\s*Abstract:\s*", "", abstract, flags=re.IGNORECASE)
    abstract = " ".join(abstract.split())
    title = " ".join(title.split())

    if not title and not abstract:
        return None

    return {
        "origin": "arxiv",
        "arxiv_id": arxiv_id,
        "title": title or "Unknown",
        "authors": [],
        "abstract": abstract,
        "published": None,
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "fallback_source": "arxiv_abs_html",
    }


def ingest_source(state: dict) -> dict:
    source_type = state.get("source_type")

    if source_type == "pdf":
        return {"source_manifest": {"origin": "pdf"}}

    arxiv_id = state.get("arxiv_id")
    if not arxiv_id:
        return {"errors": ["ingest_source: missing arxiv_id"]}

    params = {"search_query": f"id:{arxiv_id}", "start": 0, "max_results": 1}
    query = urllib.parse.urlencode(params)

    # Use multiple endpoints for better resilience to transient arXiv API/network failures.
    api_urls = [
        f"https://export.arxiv.org/api/query?{query}",
        f"http://export.arxiv.org/api/query?{query}",
        f"https://arxiv.org/api/query?{query}",
        f"http://arxiv.org/api/query?{query}",
    ]

    last_error: str | None = None
    for api_url in api_urls:
        try:
            feed = _parse_arxiv_feed(api_url)
            if getattr(feed, "bozo", False):
                bozo_exc = getattr(feed, "bozo_exception", None)
                if bozo_exc:
                    last_error = str(bozo_exc)

            if not feed.entries:
                continue

            entry = feed.entries[0]
            title = entry.title.replace("\n", " ").strip()
            abstract = entry.summary.replace("\n", " ").strip()
            authors = [a.name for a in entry.authors]
            published = getattr(entry, "published", None)
            pdf_url = _pick_pdf_url(entry)

            return {
                "source_manifest": {
                    "origin": "arxiv",
                    "arxiv_id": arxiv_id,
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "published": published,
                    "pdf_url": pdf_url,
                }
            }
        except Exception as e:
            last_error = str(e)
            continue

    if last_error:
        try:
            fallback_manifest = _fetch_arxiv_abs_fallback(arxiv_id)
            if fallback_manifest:
                return {"source_manifest": fallback_manifest}
        except Exception:
            pass
        return {
            "errors": [
                f"ingest_source: {last_error} (arXiv API temporarily unavailable, please retry)"
            ]
        }
    return {
        "errors": [
            f"ingest_source: no arXiv entry for {arxiv_id} "
            f"(请核对 ID 是否在 https://arxiv.org 存在，新稿可能尚未入库)"
        ]
    }

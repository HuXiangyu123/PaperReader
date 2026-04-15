from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

SourceTier = Literal["A", "B", "C", "D"]

_TIER_A_DOMAINS = {
    "arxiv.org",
    "doi.org",
    "semanticscholar.org",
    "acm.org",
    "dl.acm.org",
    "ieee.org",
    "ieeexplore.ieee.org",
    "nature.com",
    "science.org",
    "springer.com",
    "link.springer.com",
    "wiley.com",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "proceedings.neurips.cc",
    "openreview.net",
    "aclanthology.org",
    "proceedings.mlr.press",
}

_TIER_B_DOMAINS = {
    "github.com",
    "huggingface.co",
    "blog.openai.com",
    "ai.googleblog.com",
    "deepmind.google",
    "distill.pub",
    "lilianweng.github.io",
    "paperswithcode.com",
}

_TIER_C_DOMAINS = {
    "wikipedia.org",
    "en.wikipedia.org",
    "stackoverflow.com",
    "towardsdatascience.com",
}


def classify_url(url: str) -> SourceTier:
    """Classify a URL into source tier A/B/C/D."""
    if not url or not url.startswith(("http://", "https://")):
        return "D"

    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        host = host.lower()
    except Exception:
        return "D"

    # Check exact match and suffix match for Tier A
    for domain in _TIER_A_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "A"

    # Tier B
    for domain in _TIER_B_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "B"

    # Tier C exact domains
    for domain in _TIER_C_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return "C"

    # Tier C: .edu and .gov domains
    if host.endswith(".edu") or host.endswith(".gov"):
        return "C"

    return "D"

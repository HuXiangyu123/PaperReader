from __future__ import annotations

import re

REQUIRED_SECTIONS = {"标题", "核心贡献", "方法概述", "关键实验", "局限性"}


def check_structure(report_md: str) -> dict:
    """Check if report has all required sections."""
    found = set()
    for line in report_md.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            found.add(section)
    missing = REQUIRED_SECTIONS - found
    return {"pass": len(missing) == 0, "missing": list(missing), "found": list(found)}


def check_citation_format(report_md: str) -> dict:
    """Check citations section exists and has proper format."""
    has_section = bool(
        re.search(r"^##\s+引用", report_md, re.MULTILINE)
        or re.search(r"^##\s+参考文献", report_md, re.MULTILINE)
        or re.search(r"^##\s+References", report_md, re.MULTILINE)
    )

    citation_lines = re.findall(r"^\s*-\s+\[", report_md, re.MULTILINE)
    return {
        "pass": has_section and len(citation_lines) > 0,
        "has_section": has_section,
        "citation_count": len(citation_lines),
    }


def check_must_include(report_md: str, keywords: list[str]) -> dict:
    """Check all required keywords appear in report."""
    report_lower = report_md.lower()
    results = {}
    for kw in keywords:
        results[kw] = kw.lower() in report_lower
    return {"pass": all(results.values()), "keywords": results}


def check_min_citations(report_md: str, min_count: int) -> dict:
    """Check minimum citation count."""
    url_pattern = r"https?://\S+"
    urls = re.findall(url_pattern, report_md)
    return {"pass": len(urls) >= min_count, "found": len(urls), "required": min_count}


def check_cost_guard(tokens_used: int, max_tokens: int = 50000) -> dict:
    """Check token usage is within budget."""
    return {"pass": tokens_used <= max_tokens, "tokens_used": tokens_used, "max": max_tokens}


def run_layer1(report_md: str, case: dict, tokens_used: int = 0) -> dict:
    """Run all Layer 1 checks. Returns {pass: bool, checks: {...}}."""
    checks: dict[str, dict] = {}

    if case.get("expect_error"):
        is_error = report_md.startswith("Error") or "error" in report_md.lower()[:200]
        checks["error_handled"] = {"pass": is_error}
        return {"pass": is_error, "checks": checks}

    checks["structure"] = check_structure(report_md)
    checks["citation_format"] = check_citation_format(report_md)

    if "must_include" in case:
        checks["must_include"] = check_must_include(report_md, case["must_include"])

    if "min_citations" in case:
        checks["min_citations"] = check_min_citations(report_md, case["min_citations"])

    checks["cost_guard"] = check_cost_guard(tokens_used)

    all_pass = all(c["pass"] for c in checks.values())
    return {"pass": all_pass, "checks": checks}

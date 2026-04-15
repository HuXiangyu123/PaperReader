from __future__ import annotations

from src.models.report import FinalReport


def check_claim_support_rate(final: FinalReport, threshold: float = 0.6) -> dict:
    """Primary signal: what fraction of claims are grounded or partial."""
    stats = final.grounding_stats
    total = stats.total_claims
    if total == 0:
        return {"pass": True, "rate": 1.0, "threshold": threshold, "detail": "no claims"}

    supported = stats.grounded + stats.partial
    rate = supported / total
    return {"pass": rate >= threshold, "rate": round(rate, 3), "threshold": threshold}


def check_citation_resolution_rate(final: FinalReport, threshold: float = 0.7) -> dict:
    """What fraction of citations are reachable."""
    total = len(final.citations)
    if total == 0:
        return {"pass": True, "rate": 1.0, "threshold": threshold, "detail": "no citations"}

    reachable = sum(1 for c in final.citations if c.reachable is True)
    rate = reachable / total
    return {"pass": rate >= threshold, "rate": round(rate, 3), "threshold": threshold}


def check_unsupported_claim_count(final: FinalReport, max_count: int = 3) -> dict:
    """Flag if too many claims are fully ungrounded."""
    stats = final.grounding_stats
    return {
        "pass": stats.ungrounded <= max_count,
        "ungrounded": stats.ungrounded,
        "max": max_count,
    }


def check_abstention_compliance(final: FinalReport) -> dict:
    """Verify abstained claims are properly marked (have no supported citations)."""
    violations = []
    for claim in final.claims:
        if claim.overall_status == "abstained":
            # Should have no supported evidence
            has_support = any(s.support_status == "supported" for s in claim.supports)
            if has_support:
                violations.append(claim.id)
    return {"pass": len(violations) == 0, "violations": violations}


def check_source_tier_ratio(final: FinalReport, min_a_ratio: float = 0.3) -> dict:
    """Check that at least min_a_ratio of citations are Tier A."""
    stats = final.grounding_stats
    return {
        "pass": stats.tier_a_ratio >= min_a_ratio,
        "tier_a_ratio": round(stats.tier_a_ratio, 3),
        "tier_b_ratio": round(stats.tier_b_ratio, 3),
        "min_a_ratio": min_a_ratio,
    }


def run_layer2(final: FinalReport, case: dict | None = None) -> dict:
    """Run all Layer 2 grounding checks."""
    if case and case.get("expect_error"):
        return {"pass": True, "checks": {}, "detail": "error case — L2 skipped"}

    checks = {}
    checks["claim_support_rate"] = check_claim_support_rate(final)
    checks["citation_resolution"] = check_citation_resolution_rate(final)
    checks["unsupported_count"] = check_unsupported_claim_count(final)
    checks["abstention_compliance"] = check_abstention_compliance(final)
    checks["source_tier_ratio"] = check_source_tier_ratio(final)

    all_pass = all(c["pass"] for c in checks.values())
    return {"pass": all_pass, "checks": checks}

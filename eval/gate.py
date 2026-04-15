from __future__ import annotations

DEFAULT_THRESHOLDS = {
    "l1_pass_rate": 0.9,  # 90% of cases must pass L1
    "l2_pass_rate": 0.7,  # 70% of cases must pass L2
    "max_regressions": 0,  # zero regressions from baseline
    "max_cost_tokens": 50000,  # per-case token budget
}


def check_gate(
    run_result: dict,
    thresholds: dict | None = None,
    diff: dict | None = None,
) -> dict:
    """Check if eval results pass the release gate."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    results = run_result.get("results", [])
    total = len(results)
    if total == 0:
        return {"pass": False, "reason": "no results"}

    checks = {}

    # L1 pass rate
    l1_passed = sum(1 for r in results if r.get("layer1", {}).get("pass", False))
    l1_rate = l1_passed / total
    checks["l1_pass_rate"] = {
        "pass": l1_rate >= t["l1_pass_rate"],
        "rate": round(l1_rate, 3),
        "threshold": t["l1_pass_rate"],
    }

    # L2 pass rate (if available)
    l2_results = [r for r in results if "layer2" in r]
    if l2_results:
        l2_passed = sum(1 for r in l2_results if r.get("layer2", {}).get("pass", False))
        l2_rate = l2_passed / len(l2_results)
        checks["l2_pass_rate"] = {
            "pass": l2_rate >= t["l2_pass_rate"],
            "rate": round(l2_rate, 3),
            "threshold": t["l2_pass_rate"],
        }

    # Regression check
    if diff:
        reg_count = diff.get("regression_count", 0)
        checks["regressions"] = {
            "pass": reg_count <= t["max_regressions"],
            "count": reg_count,
            "max": t["max_regressions"],
        }

    all_pass = all(c["pass"] for c in checks.values())
    return {"pass": all_pass, "checks": checks}

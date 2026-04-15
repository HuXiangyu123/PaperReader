from __future__ import annotations

import json


def load_run(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def diff_runs(baseline_path: str, current_path: str) -> dict:
    """Compare two eval runs. Returns diff summary."""
    baseline = load_run(baseline_path)
    current = load_run(current_path)

    b_results = {r["id"]: r for r in baseline.get("results", [])}
    c_results = {r["id"]: r for r in current.get("results", [])}

    all_ids = sorted(set(b_results.keys()) | set(c_results.keys()))

    regressions = []
    improvements = []
    unchanged = []
    new_cases = []

    for case_id in all_ids:
        b = b_results.get(case_id)
        c = c_results.get(case_id)

        if not b:
            new_cases.append(case_id)
            continue
        if not c:
            regressions.append({"id": case_id, "reason": "missing in current run"})
            continue

        b_pass = b.get("layer1", {}).get("pass", False)
        c_pass = c.get("layer1", {}).get("pass", False)

        if b_pass and not c_pass:
            regressions.append({"id": case_id, "reason": "was passing, now failing"})
        elif not b_pass and c_pass:
            improvements.append(case_id)
        else:
            unchanged.append(case_id)

    return {
        "baseline": baseline_path,
        "current": current_path,
        "regressions": regressions,
        "improvements": improvements,
        "unchanged": unchanged,
        "new_cases": new_cases,
        "regression_count": len(regressions),
    }


def diff_to_markdown(diff: dict) -> str:
    """Format diff as markdown."""
    lines = ["# Eval Diff Report\n"]
    lines.append(f"- Baseline: `{diff['baseline']}`")
    lines.append(f"- Current: `{diff['current']}`\n")

    if diff["regressions"]:
        lines.append("## Regressions\n")
        for r in diff["regressions"]:
            lines.append(f"- **{r['id']}**: {r['reason']}")
    else:
        lines.append("## No Regressions\n")

    if diff["improvements"]:
        lines.append("\n## Improvements\n")
        for imp in diff["improvements"]:
            lines.append(f"- {imp}")

    lines.append("\n## Summary")
    lines.append(f"- Regressions: {diff['regression_count']}")
    lines.append(f"- Improvements: {len(diff['improvements'])}")
    lines.append(f"- Unchanged: {len(diff['unchanged'])}")
    lines.append(f"- New cases: {len(diff['new_cases'])}")

    return "\n".join(lines)

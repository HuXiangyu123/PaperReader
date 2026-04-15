from __future__ import annotations

from src.models.report import VerifiedReport


def apply_policy(state: dict) -> dict:
    verified: VerifiedReport | None = state.get("verified_report")
    if not verified:
        return {"warnings": ["apply_policy: no verified_report, skipping"]}

    total = len(verified.claims)
    if total == 0:
        return {}

    grounded = sum(1 for c in verified.claims if c.overall_status == "grounded")
    partial = sum(1 for c in verified.claims if c.overall_status == "partial")

    support_ratio = (grounded + partial) / total
    current = state.get("degradation_mode", "normal")

    if current == "safe_abort":
        return {}

    if support_ratio >= 0.8:
        return {}
    elif support_ratio >= 0.5:
        new_mode = "limited" if current == "normal" else current
    else:
        new_mode = "safe_abort" if current in ("normal", "limited") else current

    if new_mode != current:
        return {"degradation_mode": new_mode}
    return {}

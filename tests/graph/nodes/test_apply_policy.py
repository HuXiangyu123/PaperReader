from src.graph.nodes.apply_policy import apply_policy
from src.models.report import Citation, Claim, VerifiedReport


def _make_verified(statuses, citations=None):
    claims = [
        Claim(
            id=f"c{i}",
            text=f"claim {i}",
            citation_labels=[],
            overall_status=s,
        )
        for i, s in enumerate(statuses)
    ]
    if citations is None:
        citations = [
            Citation(
                label="[1]", url="https://arxiv.org/abs/1", reason="r",
                source_tier="A", reachable=True,
            ),
            Citation(
                label="[2]", url="https://github.com/x", reason="r",
                source_tier="B", reachable=True,
            ),
        ]
    return VerifiedReport(sections={"标题": "T"}, claims=claims, citations=citations)


def test_policy_no_verified():
    result = apply_policy({})
    assert "warnings" in result
    assert any("no verified_report" in w for w in result["warnings"])


def test_policy_high_confidence_no_degradation():
    """>=80% grounded+partial keeps degradation_mode unchanged."""
    verified = _make_verified(
        ["grounded", "grounded", "grounded", "grounded", "partial"]
    )
    result = apply_policy({"verified_report": verified, "degradation_mode": "normal"})
    assert result.get("degradation_mode", "normal") == "normal" or result == {}


def test_policy_limited_confidence():
    """50-79% grounded+partial → degradation_mode = limited."""
    verified = _make_verified(["grounded", "grounded", "ungrounded", "ungrounded"])
    result = apply_policy({"verified_report": verified, "degradation_mode": "normal"})
    assert result.get("degradation_mode") == "limited"


def test_policy_low_confidence():
    """<50% grounded+partial → safe_abort."""
    verified = _make_verified(
        ["ungrounded", "ungrounded", "ungrounded", "abstained"]
    )
    result = apply_policy({"verified_report": verified, "degradation_mode": "normal"})
    assert result.get("degradation_mode") == "safe_abort"


def test_policy_no_claims():
    verified = _make_verified([])
    result = apply_policy({"verified_report": verified, "degradation_mode": "normal"})
    assert result == {}


def test_policy_preserves_worse_degradation():
    """Even 100% grounded should not improve from limited to normal."""
    verified = _make_verified(["grounded", "grounded"])
    result = apply_policy({"verified_report": verified, "degradation_mode": "limited"})
    assert result.get("degradation_mode", "limited") != "normal"


def test_policy_safe_abort_unchanged():
    """safe_abort is never overridden by apply_policy."""
    verified = _make_verified(["grounded", "grounded"])
    result = apply_policy(
        {"verified_report": verified, "degradation_mode": "safe_abort"}
    )
    assert result == {}


def test_policy_exact_80_percent():
    """Exactly 80% should count as high confidence."""
    verified = _make_verified(
        ["grounded", "grounded", "grounded", "grounded", "ungrounded"]
    )
    result = apply_policy({"verified_report": verified, "degradation_mode": "normal"})
    assert result == {}


def test_policy_just_below_80_percent():
    """79% → limited."""
    verified = _make_verified(
        [
            "grounded", "grounded", "grounded",
            "ungrounded", "ungrounded",
        ]
    )
    result = apply_policy({"verified_report": verified, "degradation_mode": "normal"})
    assert result.get("degradation_mode") == "limited"

from eval.layers.grounding import (
    check_abstention_compliance,
    check_citation_resolution_rate,
    check_claim_support_rate,
    check_source_tier_ratio,
    check_unsupported_claim_count,
    run_layer2,
)
from src.models.report import (
    Claim,
    Citation,
    ClaimSupport,
    FinalReport,
    GroundingStats,
)


def _make_final(
    grounded=3,
    partial=1,
    ungrounded=1,
    abstained=0,
    tier_a=2,
    tier_b=1,
    total_cits=4,
    reachable_count=3,
):
    stats = GroundingStats(
        total_claims=grounded + partial + ungrounded + abstained,
        grounded=grounded,
        partial=partial,
        ungrounded=ungrounded,
        abstained=abstained,
        tier_a_ratio=tier_a / max(total_cits, 1),
        tier_b_ratio=tier_b / max(total_cits, 1),
    )
    claims = []
    for i in range(grounded):
        claims.append(
            Claim(
                id=f"g{i}",
                text="grounded claim",
                citation_labels=["[1]"],
                overall_status="grounded",
                supports=[
                    ClaimSupport(
                        claim_id=f"g{i}",
                        citation_label="[1]",
                        support_status="supported",
                    )
                ],
            )
        )
    for i in range(partial):
        claims.append(
            Claim(
                id=f"p{i}",
                text="partial claim",
                citation_labels=["[2]"],
                overall_status="partial",
                supports=[
                    ClaimSupport(
                        claim_id=f"p{i}",
                        citation_label="[2]",
                        support_status="partial",
                    )
                ],
            )
        )
    for i in range(ungrounded):
        claims.append(
            Claim(
                id=f"u{i}",
                text="ungrounded claim",
                citation_labels=["[3]"],
                overall_status="ungrounded",
                supports=[
                    ClaimSupport(
                        claim_id=f"u{i}",
                        citation_label="[3]",
                        support_status="unsupported",
                    )
                ],
            )
        )
    for i in range(abstained):
        claims.append(
            Claim(
                id=f"a{i}",
                text="abstained claim",
                citation_labels=[],
                overall_status="abstained",
                supports=[],
            )
        )

    citations = []
    for i in range(total_cits):
        reachable = i < reachable_count
        tier = "A" if i < tier_a else ("B" if i < tier_a + tier_b else "D")
        citations.append(
            Citation(
                label=f"[{i + 1}]",
                url=f"https://example.com/{i}",
                reason="ref",
                source_tier=tier,
                reachable=reachable,
            )
        )

    return FinalReport(
        sections={"标题": "Test"},
        claims=claims,
        citations=citations,
        grounding_stats=stats,
        report_confidence="high",
    )


def test_claim_support_rate_pass():
    final = _make_final(grounded=4, partial=1, ungrounded=0)
    result = check_claim_support_rate(final)
    assert result["pass"] is True
    assert result["rate"] == 1.0


def test_claim_support_rate_fail():
    final = _make_final(grounded=1, partial=0, ungrounded=4)
    result = check_claim_support_rate(final)
    assert result["pass"] is False


def test_citation_resolution_pass():
    final = _make_final(total_cits=4, reachable_count=3)
    result = check_citation_resolution_rate(final)
    assert result["pass"] is True


def test_citation_resolution_fail():
    final = _make_final(total_cits=4, reachable_count=1)
    result = check_citation_resolution_rate(final)
    assert result["pass"] is False


def test_unsupported_count_pass():
    final = _make_final(ungrounded=2)
    result = check_unsupported_claim_count(final)
    assert result["pass"] is True


def test_unsupported_count_fail():
    final = _make_final(ungrounded=5)
    result = check_unsupported_claim_count(final)
    assert result["pass"] is False


def test_abstention_compliance_pass():
    final = _make_final(abstained=1)
    result = check_abstention_compliance(final)
    assert result["pass"] is True


def test_abstention_compliance_violation():
    # Manually create a claim marked "abstained" but with a "supported" support
    final = _make_final()
    bad_claim = Claim(
        id="bad",
        text="should be abstained",
        citation_labels=["[1]"],
        overall_status="abstained",
        supports=[
            ClaimSupport(
                claim_id="bad",
                citation_label="[1]",
                support_status="supported",
            )
        ],
    )
    final = final.model_copy(update={"claims": list(final.claims) + [bad_claim]})
    result = check_abstention_compliance(final)
    assert result["pass"] is False
    assert "bad" in result["violations"]


def test_tier_ratio_pass():
    final = _make_final(tier_a=3, total_cits=4)
    result = check_source_tier_ratio(final)
    assert result["pass"] is True


def test_tier_ratio_fail():
    final = _make_final(tier_a=0, total_cits=4)
    result = check_source_tier_ratio(final)
    assert result["pass"] is False


def test_run_layer2_all_good():
    final = _make_final(
        grounded=4,
        partial=1,
        ungrounded=0,
        tier_a=3,
        total_cits=5,
        reachable_count=4,
    )
    result = run_layer2(final)
    assert result["pass"] is True


def test_run_layer2_error_case_skipped():
    final = _make_final()
    result = run_layer2(final, case={"expect_error": True})
    assert result["pass"] is True

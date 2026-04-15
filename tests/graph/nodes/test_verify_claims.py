from unittest.mock import patch

from src.graph.nodes.verify_claims import verify_claims
from src.models.report import (
    Citation,
    Claim,
    ClaimSupport,
    ResolvedReport,
)


def _make_resolved(claims=None, citations=None):
    if claims is None:
        claims = [Claim(id="c1", text="achieves SOTA", citation_labels=["[1]"])]
    if citations is None:
        citations = [
            Citation(
                label="[1]",
                url="https://arxiv.org/abs/1706.03762",
                reason="paper",
                source_tier="A",
                reachable=True,
                fetched_content="The model achieves state-of-the-art results",
            )
        ]
    return ResolvedReport(sections={"标题": "Test"}, claims=claims, citations=citations)


def test_verify_no_resolved():
    result = verify_claims({})
    assert "warnings" in result
    assert any("no resolved_report" in w for w in result["warnings"])


def test_verify_supported_claim():
    resolved = _make_resolved()
    mock_support = ClaimSupport(
        claim_id="c1",
        citation_label="[1]",
        support_status="supported",
        reason="direct evidence",
        judge_confidence=0.9,
    )
    with patch(
        "src.graph.nodes.verify_claims.judge_claim_citation",
        return_value=mock_support,
    ):
        result = verify_claims({"resolved_report": resolved})

    verified = result["verified_report"]
    assert verified.claims[0].overall_status == "grounded"
    assert len(verified.claims[0].supports) == 1
    assert verified.claims[0].supports[0].support_status == "supported"


def test_verify_partial_claim():
    resolved = _make_resolved()
    mock_support = ClaimSupport(
        claim_id="c1",
        citation_label="[1]",
        support_status="partial",
        reason="partial evidence only",
        judge_confidence=0.6,
    )
    with patch(
        "src.graph.nodes.verify_claims.judge_claim_citation",
        return_value=mock_support,
    ):
        result = verify_claims({"resolved_report": resolved})

    assert result["verified_report"].claims[0].overall_status == "partial"


def test_verify_unsupported_claim():
    resolved = _make_resolved()
    mock_support = ClaimSupport(
        claim_id="c1",
        citation_label="[1]",
        support_status="unsupported",
        reason="contradicts evidence",
    )
    with patch(
        "src.graph.nodes.verify_claims.judge_claim_citation",
        return_value=mock_support,
    ):
        result = verify_claims({"resolved_report": resolved})

    assert result["verified_report"].claims[0].overall_status == "ungrounded"


def test_verify_no_llm_all_unverifiable():
    """When LLM is unavailable, judge returns unverifiable → overall abstained."""
    resolved = _make_resolved()
    with patch(
        "src.agent.settings.Settings.from_env",
        side_effect=Exception("no env"),
    ):
        result = verify_claims({"resolved_report": resolved})

    verified = result["verified_report"]
    assert verified.claims[0].overall_status == "abstained"
    assert verified.claims[0].supports[0].support_status == "unverifiable"


def test_verify_unknown_citation_ref():
    claims = [Claim(id="c1", text="claim", citation_labels=["[99]"])]
    citations = [Citation(label="[1]", url="https://example.com", reason="r")]
    resolved = _make_resolved(claims=claims, citations=citations)

    result = verify_claims({"resolved_report": resolved})

    assert "warnings" in result
    assert any("[99]" in w for w in result["warnings"])
    assert result["verified_report"].claims[0].overall_status == "abstained"


def test_verify_no_citation_labels():
    claims = [Claim(id="c1", text="uncited claim", citation_labels=[])]
    resolved = _make_resolved(claims=claims)

    result = verify_claims({"resolved_report": resolved})

    assert result["verified_report"].claims[0].overall_status == "abstained"
    assert result["verified_report"].claims[0].supports == []


def test_verify_multiple_citations_mixed():
    claims = [Claim(id="c1", text="claim", citation_labels=["[1]", "[2]"])]
    citations = [
        Citation(
            label="[1]", url="https://arxiv.org/abs/1", reason="paper",
            source_tier="A", reachable=True, fetched_content="evidence",
        ),
        Citation(
            label="[2]", url="https://github.com/x", reason="code",
            source_tier="B", reachable=True, fetched_content="more evidence",
        ),
    ]
    resolved = _make_resolved(claims=claims, citations=citations)

    def mock_judge(claim_id, claim_text, citation_label, citation_content, llm=None):
        status = "supported" if citation_label == "[1]" else "unsupported"
        return ClaimSupport(
            claim_id=claim_id,
            citation_label=citation_label,
            support_status=status,
            reason="test",
        )

    with patch(
        "src.graph.nodes.verify_claims.judge_claim_citation",
        side_effect=mock_judge,
    ):
        result = verify_claims({"resolved_report": resolved})

    verified = result["verified_report"]
    assert len(verified.claims[0].supports) == 2
    assert verified.claims[0].overall_status == "grounded"


def test_verify_preserves_sections_and_citations():
    resolved = _make_resolved()
    mock_support = ClaimSupport(
        claim_id="c1", citation_label="[1]",
        support_status="supported", reason="ok",
    )
    with patch(
        "src.graph.nodes.verify_claims.judge_claim_citation",
        return_value=mock_support,
    ):
        result = verify_claims({"resolved_report": resolved})

    verified = result["verified_report"]
    assert verified.sections == resolved.sections
    assert len(verified.citations) == len(resolved.citations)

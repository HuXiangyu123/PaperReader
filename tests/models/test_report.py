from src.models.report import (
    Citation,
    ClaimSupport,
    Claim,
    GroundingStats,
    DraftReport,
    ReportFrame,
    ResolvedReport,
    VerifiedReport,
    FinalReport,
)


def test_citation_defaults():
    c = Citation(label="[1]", url="https://arxiv.org/abs/1706.03762", reason="original paper")
    assert c.source_tier is None
    assert c.reachable is None


def test_claim_support():
    cs = ClaimSupport(
        claim_id="c1",
        citation_label="[1]",
        support_status="supported",
        evidence_excerpt="we propose the Transformer",
    )
    assert cs.support_status == "supported"


def test_claim_with_supports():
    c = Claim(id="c1", text="Transformer uses attention only", citation_labels=["[1]"])
    assert c.overall_status == "ungrounded"
    assert c.supports == []


def test_grounding_stats():
    gs = GroundingStats(
        total_claims=10,
        grounded=8,
        partial=1,
        ungrounded=0,
        abstained=1,
        tier_a_ratio=0.6,
        tier_b_ratio=0.2,
    )
    assert gs.grounded + gs.partial + gs.ungrounded + gs.abstained == gs.total_claims


def test_draft_report_roundtrip():
    dr = DraftReport(
        sections={"title": "Attention"},
        claims=[Claim(id="c1", text="test", citation_labels=["[1]"])],
        citations=[Citation(label="[1]", url="https://example.com", reason="test")],
    )
    data = dr.model_dump()
    dr2 = DraftReport.model_validate(data)
    assert dr2.sections == dr.sections


def test_final_report_confidence():
    fr = FinalReport(
        sections={},
        claims=[],
        citations=[],
        grounding_stats=GroundingStats(
            total_claims=0,
            grounded=0,
            partial=0,
            ungrounded=0,
            abstained=0,
            tier_a_ratio=0,
            tier_b_ratio=0,
        ),
        report_confidence="high",
    )
    assert fr.report_confidence == "high"


def test_report_frame_roundtrip():
    frame = ReportFrame(
        title="Attention",
        paper_type="regular",
        mode="full",
        sections={"I. 摘要与研究动机": "content"},
        outline=None,
        claims=[],
        citations=[],
    )
    restored = ReportFrame.model_validate(frame.model_dump())
    assert restored.title == "Attention"

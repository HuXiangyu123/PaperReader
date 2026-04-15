import json
from unittest.mock import MagicMock

from src.verification.claim_judge import judge_claim_citation


def _mock_llm_response(data: dict):
    resp = MagicMock()
    resp.content = json.dumps(data)
    llm = MagicMock()
    llm.invoke.return_value = resp
    return llm


def test_judge_supported():
    llm = _mock_llm_response({
        "support_status": "supported",
        "evidence_excerpt": "achieves state-of-the-art BLEU score",
        "reason": "Evidence directly states the claim",
        "confidence": 0.95,
    })
    result = judge_claim_citation(
        claim_id="c1",
        claim_text="Transformer achieves SOTA",
        citation_label="[1]",
        citation_content="The model achieves state-of-the-art BLEU score of 28.4",
        llm=llm,
    )
    assert result.support_status == "supported"
    assert result.judge_confidence == 0.95
    assert result.claim_id == "c1"
    assert result.citation_label == "[1]"


def test_judge_unsupported():
    llm = _mock_llm_response({
        "support_status": "unsupported",
        "reason": "Evidence contradicts the claim",
        "confidence": 0.8,
    })
    result = judge_claim_citation(
        claim_id="c2",
        claim_text="RNN is better",
        citation_label="[2]",
        citation_content="Transformer outperforms RNN",
        llm=llm,
    )
    assert result.support_status == "unsupported"


def test_judge_no_content():
    result = judge_claim_citation(
        claim_id="c1",
        claim_text="Some claim",
        citation_label="[1]",
        citation_content=None,
    )
    assert result.support_status == "unverifiable"
    assert "No citation content" in result.reason


def test_judge_no_llm():
    result = judge_claim_citation(
        claim_id="c1",
        claim_text="Some claim",
        citation_label="[1]",
        citation_content="Some content",
        llm=None,
    )
    assert result.support_status == "unverifiable"


def test_judge_llm_error():
    llm = MagicMock()
    llm.invoke.side_effect = Exception("LLM timeout")
    result = judge_claim_citation(
        claim_id="c1",
        claim_text="claim",
        citation_label="[1]",
        citation_content="content",
        llm=llm,
    )
    assert result.support_status == "unverifiable"
    assert "Judge error" in result.reason


def test_judge_invalid_json():
    resp = MagicMock()
    resp.content = "This is not JSON"
    llm = MagicMock()
    llm.invoke.return_value = resp
    result = judge_claim_citation(
        claim_id="c1",
        claim_text="claim",
        citation_label="[1]",
        citation_content="content",
        llm=llm,
    )
    assert result.support_status == "unverifiable"


def test_judge_with_markdown_fences():
    data = {
        "support_status": "partial",
        "reason": "Partially supports",
        "confidence": 0.6,
    }
    resp = MagicMock()
    resp.content = f"```json\n{json.dumps(data)}\n```"
    llm = MagicMock()
    llm.invoke.return_value = resp
    result = judge_claim_citation(
        claim_id="c1",
        claim_text="claim",
        citation_label="[1]",
        citation_content="content",
        llm=llm,
    )
    assert result.support_status == "partial"

from src.models.paper import PaperMetadata, RagResult, WebResult, EvidenceBundle, NormalizedDocument


def test_paper_metadata_minimal():
    m = PaperMetadata(title="Attention", authors=["Vaswani"], abstract="We propose...")
    assert m.pdf_url is None
    assert m.published is None


def test_paper_metadata_full():
    m = PaperMetadata(
        title="Attention Is All You Need",
        authors=["Vaswani", "Shazeer"],
        abstract="The dominant...",
        pdf_url="https://arxiv.org/pdf/1706.03762",
        published="2017-06-12",
    )
    assert m.pdf_url.startswith("https://")


def test_evidence_bundle_empty():
    eb = EvidenceBundle(rag_results=[], web_results=[])
    assert len(eb.rag_results) == 0


def test_normalized_document():
    meta = PaperMetadata(title="T", authors=["A"], abstract="Ab")
    nd = NormalizedDocument(
        metadata=meta,
        document_text="full text",
        document_sections={"intro": "..."},
        source_manifest={"origin": "arxiv", "arxiv_id": "1706.03762"},
    )
    assert nd.metadata.title == "T"
    assert "intro" in nd.document_sections

from src.graph.builder import build_report_graph


def test_graph_compiles():
    graph = build_report_graph()
    assert graph is not None


def test_graph_has_expected_nodes():
    graph = build_report_graph()
    node_names = set(graph.nodes.keys())
    expected = {
        "input_parse",
        "ingest_source",
        "extract_document_text",
        "normalize_metadata",
        "retrieve_evidence",
        "classify_paper_type",
        "draft_report",
        "report_frame",
        "survey_intro_outline",
        "repair_report",
        "resolve_citations",
        "verify_claims",
        "apply_policy",
        "format_output",
    }
    assert expected.issubset(node_names)

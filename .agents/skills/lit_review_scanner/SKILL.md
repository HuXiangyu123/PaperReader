name: lit_review_scanner
description: Multi-source academic literature scan and candidate ranking. Fetches papers from arXiv/Semantic Scholar, deduplicates by arXiv ID, and ranks by relevance to research topic.
backend: local_function
default_agent: retriever
output_artifact_type: rag_result
visibility: both
tags:
  - retrieval
  - multi-source
  - arxiv
  - academic
  - research
input_schema:
  topic: string
  sub_questions: array
  max_results: integer (default: 30)
  year_filter: string (optional)

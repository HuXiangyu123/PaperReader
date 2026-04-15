name: writing_scaffold_generator
description: Generate structured writing scaffold for academic survey papers. Produces Title, Abstract, Introduction, and section outlines based on research topic, paper cards, and comparison matrix.
backend: local_function
default_agent: analyst
output_artifact_type: report_outline
visibility: both
tags:
  - writing
  - scaffold
  - outline
  - survey
  - generation
input_schema:
  topic: string
  paper_cards: array
  comparison_matrix: object (optional)
  desired_length: string (optional, "short" | "medium" | "long")

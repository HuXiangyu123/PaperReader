name: comparison_matrix_builder
description: Build a structured comparison matrix from paper cards. Extracts method descriptions, dataset benchmarks, and limitations from paper metadata to produce a tabular comparison for survey report writing.
backend: local_function
default_agent: analyst
output_artifact_type: comparison_matrix
visibility: both
tags:
  - analysis
  - comparison
  - papers
  - survey
  - matrix
input_schema:
  paper_cards: array
  compare_dimensions: array (default: ["methods", "datasets", "benchmarks", "limitations"])
  format: string ("table" | "json")

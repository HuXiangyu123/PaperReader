name: experiment_replicator
description: Analyze experimental settings and results from academic papers. Extracts dataset splits, hyperparameter ranges, evaluation metrics, and baseline comparisons to assess reproducibility.
backend: local_function
default_agent: analyst
output_artifact_type: experiment_analysis
visibility: both
tags:
  - experiment
  - replication
  - analysis
  - reproducibility
  - datasets
input_schema:
  paper_cards: array
  focus_papers: array (optional, focus on specific papers)

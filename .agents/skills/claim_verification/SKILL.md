name: claim_verification
description: Verify scientific claims against evidence. Checks whether each claim in a draft report is grounded by retrieved citations, categorizing as grounded / partial / ungrounded / abstained.
backend: local_function
default_agent: reviewer
output_artifact_type: verified_report
visibility: both
tags:
  - verification
  - claims
  - evidence
  - grounding
  - review
input_schema:
  draft_report: object
  evidence_sources: array
  claim_ids: array (optional, verify specific claims only)

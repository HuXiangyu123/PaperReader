# RAG Eval Improvement Timeline

> Date: 2026-04-11
> Scope: SciFact public benchmark + historical smoke results
> Purpose: record improvements over time and show which module additions produced measurable gains

---

## 1. Timeline

### 2026-04-10: Smoke Baseline

At this stage the system had a working retrieval pipeline, but eval was still running on a very small handcrafted smoke set.

Result snapshot:

- `Overall Recall@50 = 83.33%`
- `MRR = 0.667`
- `1` failure case (`smoke-006`, MARL Survey not ingested)
- `Evidence Recall@25 = 0.0000`

Interpretation:

- Paper-level retrieval already worked for most smoke cases
- The main missing pieces were corpus completeness and evidence retrieval

Reference:

- [nextpromote_rag.md](/Users/artorias/devpro/PaperReader_agent/docs/active/phase/phase2/nextpromote_rag.md)

### 2026-04-11: Public Benchmark Aligned To PostgreSQL Corpus

SciFact regression and full benchmark were aligned to the local PostgreSQL corpus.

Corpus status after alignment:

- `regression`: `29` gold papers aligned
- `full`: `199` gold papers aligned
- Database reached `documents=222`, `canonical_papers=220`, `coarse_chunks=224`, `fine_chunks=2087`

This turned eval from "code-path verification" into reproducible public-benchmark replay.

### 2026-04-11: Evidence Retrieval Became Effective

After fixing:

- runner-side `ChunkRetriever` initialization
- `sub_questions` dict payload normalization
- lexical fallback when `rank_bm25` is unavailable

the `keyword_evidence` strategy stopped being a no-op and began producing strong Layer 3 gains.

### 2026-04-11: Grounding Layer Connected

After integrating:

- research-side `resolve_citations -> verify_claims -> format_output`
- eval-side projection from retrieved papers/chunks into grounding records
- support-status based Layer 4 scoring

grounding was no longer a placeholder `0.0`.

---

## 2. Ablation: Evidence Module

### Regression Benchmark

Same benchmark, same corpus, only strategy changed:

| Strategy | Paper Recall@50 | Evidence Recall@25 | Grounding Score |
|---|---:|---:|---:|
| `keyword_only` | `1.0000` | `0.0000` | `0.5000` |
| `keyword_evidence` | `1.0000` | `0.8306` | `0.7000` |

Interpretation:

- Paper retrieval stayed identical
- Evidence retrieval improved from `0.0000` to `0.8306`
- Grounding also improved from `0.5000` to `0.7000`

This is strong evidence that the evidence module adds value beyond paper retrieval.

Source reports:

- [2026-04-11-rag-regression-keyword_only.json](/Users/artorias/devpro/PaperReader_agent/output/rageval/2026-04-11-rag-regression-keyword_only.json)
- [2026-04-11-rag-regression-keyword_evidence.json](/Users/artorias/devpro/PaperReader_agent/output/rageval/2026-04-11-rag-regression-keyword_evidence.json)
- [2026-04-11-rag-regression-grounding-comparison.json](/Users/artorias/devpro/PaperReader_agent/output/rageval/2026-04-11-rag-regression-grounding-comparison.json)

### Full Benchmark

Same benchmark, same corpus, only strategy changed:

| Strategy | Paper Recall@50 | Evidence Recall@25 | Grounding Score |
|---|---:|---:|---:|
| `keyword_only` | `0.8152` | `0.0000` | `0.4840` |
| `keyword_evidence` | `0.8152` | `0.8781` | `0.7927` |

Interpretation:

- Paper retrieval stayed constant
- Evidence retrieval improved by `+0.8781`
- Grounding improved by `+0.3086`

This shows the evidence module materially improves downstream support quality, not only intermediate Layer 3 metrics.

Source reports:

- [2026-04-11-rag-full-comparison.json](/Users/artorias/devpro/PaperReader_agent/output/rageval/2026-04-11-rag-full-comparison.json)
- [2026-04-11-rag-full-grounding-comparison.json](/Users/artorias/devpro/PaperReader_agent/output/rageval/2026-04-11-rag-full-grounding-comparison.json)

---

## 3. Ablation: Grounding Integration

This comparison isolates the effect of turning on grounding. The benchmark corpus and retrieval metrics stay the same; only Layer 4 changes from placeholder to real scoring.

### Full Benchmark, Before vs After Grounding

| Stage | Paper Recall@50 | Evidence Recall@25 | Grounding Score |
|---|---:|---:|---:|
| Before grounding integration | `0.8152` | `0.4391` | `0.0000` |
| After grounding integration | `0.8152` | `0.4391` | `0.6384` |

Interpretation:

- Paper retrieval did not change
- Evidence retrieval did not change
- Grounding score moved from placeholder `0.0000` to measurable `0.6384`

That means the grounding layer is now contributing real signal instead of a stubbed metric.

### Full Benchmark, Per-Strategy Reachability

After grounding integration:

- `citation_reachability = 0.9695`

Interpretation:

- Most projected citations are reachable under the current proxy grounding method
- The remaining gap is not network reachability alone; it is mostly evidence/claim alignment quality

---

## 4. Module-to-Metric Attribution

| Module addition / fix | Primary effect | Observed metric change |
|---|---|---|
| Benchmark corpus aligned to PostgreSQL | public benchmark became reproducible | smoke-only validation upgraded to regression/full SciFact replay |
| `ChunkRetriever` init + sub-question normalization | evidence retrieval started working | regression `Evidence Recall@25` from `0.0000` to `0.9333` in `keyword_evidence` baseline |
| `keyword_evidence` strategy | retrieval now uses evidence path | full `Evidence Recall@25` from `0.0000` to `0.8781` |
| Grounding integration | Layer 4 no longer placeholder | full `Grounding Score` from `0.0000` to `0.6384` |
| support-type aware grounding projection | evidence gains propagate into grounding | full `keyword_evidence` grounding `0.7927` vs `keyword_only` `0.4840` |

---

## 5. Current Best Numbers

### Regression

- Best strategy: `keyword_evidence`
- `Paper Recall@50 = 1.0000`
- `Evidence Recall@25 = 0.8306`
- `Grounding Score = 0.7000`

### Full

- Best strategy: `keyword_evidence`
- `Paper Recall@50 = 0.8152`
- `Evidence Recall@25 = 0.8781`
- `Grounding Score = 0.7927`

---

## 6. Remaining Caveats

### 6.1 Benchmark Grounding is Projection-Based, Not Report-Artifact Based

当前 benchmark 评测中的 Layer 4 grounding，本质上是 **retrieval projection**：

```
predicted_papers (检索召回)
    → predicted_chunks (evidence 召回)
        → section overlap check
            → supported / partial / unsupported
```

这是**检索层的投影**，不是**最终 report artifact 的逐-claim 解析**。两者有本质区别：

| | 当前 benchmark grounding | 终版 report grounding |
|--|------------------------|----------------------|
| 评测对象 | 检索召回的 papers + chunks | Agent 生成的 verified_report artifact |
| claim 来源 | gold_claims（人工标注） | agent 生成的 claims（无人工标注） |
| evidence 来源 | predicted_chunks（检索召回） | resolved evidence（带 source_ref + 全文） |
| 评测目标 | 检索 pipeline 质量 | Agent claim-to-evidence 支撑质量 |
| 是否需要 LLM | 否 | 是（claim verification） |

**边界含义**：benchmark 评测的是"RAG pipeline 能否正确检索"，而非"Agent 生成 report 后每个 claim 是否被 evidence 支撑"。后者需要：
1. Agent 生成包含 claim 列表的 verified_report
2. 对每个 claim 调用 LLM 判断 SUPPORT / CONTRADICT / NOT_FOUND
3. 与 gold 标准对比（需要新的 eval artifact 格式）

### 6.2 rank_bm25 未安装 — Evidence Retrieval 处于 Lexical Fallback 模式

```python
# src/corpus/search/retrievers/chunk_retriever.py
try:
    import rank_bm25
    bm25 = rank_bm25.BM25Okapi(corpus)
    scores = [float(score) for score in bm25.get_scores(tokenized_query)]
except ImportError:
    logger.warning("[ChunkRetriever] rank_bm25 未安装，回退到轻量 lexical scoring")
    # fallback: token overlap + density scoring
```

当前 evidence retrieval 使用的是**轻量 lexical fallback**（query term overlap + density），不是标准 BM25。

影响：
- 在 abstract-only corpus 上差异可能不明显（句子短，term overlap 主导）
- 换成全文 corpus 后，BM25 的 document length normalization 会更重要

安装方式：
```bash
pip install rank-bm25
```

### 6.3 Phase 5: 终版 Grounding

下一步最有价值的方向是把 **eval 直接消费最终 grounded report artifact**：

```
Agent 生成 verified_report
    → eval 解析 claim 列表
        → 对每个 claim 调用 LLM 判断 SUPPORT/CONTRADICT
            → 与 gold 标准对比
                → 真正的 "Agent claim quality" 评测
```

这将使 RAG eval 从 "pipeline 质量评测" 升级为 "Agent 科研能力评测"。

---

## 7. Recommended Next Comparisons

To make future improvements easier to interpret, keep these three report families for each major change:

1. `keyword_only`
2. `keyword_evidence`
3. `full comparison with grounding enabled`

That will keep paper retrieval, evidence retrieval, and grounding gains separately attributable.

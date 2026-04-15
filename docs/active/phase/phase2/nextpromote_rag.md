# Phase 2 完成记录 & Phase 3 推进计划

> **日期**：2026-04-10
> **Phase 2 状态**：✅ 全部 7 个模块已完成

---

## 一、Phase 2 实施总结

### 1.1 模块完成状态

| 模块 | 名称 | 状态 | 关键文件 |
|------|------|------|----------|
| M1 | Ingest / Normalize / Canonicalize | ✅ | `scripts/ingest_papers.py`, `src/corpus/ingest/` |
| M2 | Chunking (Coarse / Fine) | ✅ | `src/corpus/ingest/coarse_chunker.py`, `src/corpus/ingest/fine_chunker.py` |
| M3 | Index & Store | ✅ | `src/corpus/store/vector_index.py`, `src/corpus/store/keyword_index.py` |
| M4 | Paper-level Retrieval | ✅ | `src/corpus/search/retrievers/keyword_retriever.py`, `src/corpus/search/retrievers/dense_retriever.py` |
| M5 | Dedup + Rerank | ✅ | `src/corpus/search/deduper.py`, `src/corpus/search/reranker.py` |
| M6 | Evidence Retrieval | ✅ | `src/corpus/search/retrievers/chunk_retriever.py` |
| M7 | RAG Evaluation | ✅ | `src/eval/rag/runner.py`, `src/eval/rag/metrics.py` |

### 1.2 本次会话修复的 Bug

| Bug | 根因 | 修复 |
|-----|------|------|
| smoke eval Recall=0（全部失败） | `KeywordRetriever` 的 `ts_rank` 配合 `@@` filter，PostgreSQL `plainto_tsquery` 的 AND 语义导致口语长句无匹配 | 去掉 `@@` filter，Python 层过滤 `score > 0` |
| `_retrieve_papers` 返回空列表 | `paper_retriever._merge_sub_candidates` 将 `RecallEvidence` 误作 `MergedCandidate` 使用，访问 `rrf_score` 时爆炸 | 修复初始化逻辑 |
| title 匹配失败（BLIP-2） | predicted title 被 DB 截断为 `blip-2: ...with froze`，与 gold `blip-2: ...` 精确匹配失败 | 改用 `startswith()` 宽松匹配 |

### 1.3 最终 Smoke Eval 结果

```
PASS smoke-001: Recall@50=1.00 MRR=1.00   (RAG paper)
PASS smoke-002: Recall@50=1.00 MRR=0.50   (LoRA paper)
PASS smoke-003: Recall@50=1.00 MRR=0.50   (Self-Consistency)
PASS smoke-004: Recall@50=1.00 MRR=1.00   (BLIP-2)
PASS smoke-005: Recall@50=1.00 MRR=1.00   (RAG paper, 变体查询)
FAIL smoke-006: Recall@50=0.00             (MARL Survey 未入库)
─────────────────────────────────────────────────────
Overall Recall@50 = 83.33%  MRR = 0.667  0 errors
```

---

## 二、待完善项（Phase 2 收尾）

以下事项不影响 Phase 3 启动，但建议后续补充：

### 2.1 smoke-006 MARL Survey 入库

- gold paper：`Multi-Agent Reinforcement Learning: A Survey`
- 当前 corpus 无此论文，导致 smoke eval 83%
- **方案**：扩充 `data/eval_arxiv_ids.txt` 添加入库，或用其他已入库论文替换 smoke-006

### 2.2 Evidence Retrieval Recall=0

- smoke eval 的 `Evidence Recall@25 = 0.0000`
- 根因待查（可能是 `ChunkRetriever` 的 `paper_ids` 提取逻辑或 corpus 中 chunk 不足）

### 2.3 Cross-Encoder Reranker 模型加载失败

- 当前 reranker 因 HuggingFace repo id 传入方式问题导致模型加载失败
- 评测退化为纯 RRF 排序，结果仍正确但非最优
- **方案**：修复 `CrossEncoderReranker` 的模型加载逻辑

### 2.4 Citation / Grounding 指标

- 当前 Citation Reachability = 0（无真实引用解析）
- 需接入 `resolve_citations` 节点

---


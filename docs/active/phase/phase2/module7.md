- query 问“这篇论文怎么做 citation verification”
- 系统找到了正确论文
- 但 evidence retrieval 命中的是 introduction，而不是 method section

这种情况下：

- paper retrieval 看起来没问题
- answer 也可能“说得像对”
- 但 reviewer / grounding 一定会出问题

这正是 ChunkRAG、SF-RAG、PaperTrail 这类工作在努力解决的方向：不是只找文档，而是找**真正对当前问题有支持作用的 chunk/passages**。([arXiv](https://arxiv.org/abs/2405.07437?utm_source=chatgpt.com "Evaluation of Retrieval-Augmented Generation: A Survey"))

---

## 7.2 推荐指标

### Evidence Recall@K

gold evidence chunks 中，有多少被召回到了。

### Evidence Precision@K

召回出来的 evidence chunks 中，有多少真的是支持当前 query / sub-question 的。

### Support Span Hit Rate

如果你 gold 标注的是 section 或关键 span，可以测是否打中了该位置。

你前面自己已经把这三项列为 evidence eval 的核心指标。

---

## 7.3 在你系统里怎么落

建议 `RagEvalCase` 里增加：

```text
gold_evidence[]
- paper_title / canonical_id
- expected_section
- text_hint
- sub_question_id(optional)
```

然后对模块 6 的 `EvidenceChunk[]` 做匹配。

匹配方式可以分层：

### 宽松匹配

- 同论文
- 同 section
- 文本相似度足够高

### 严格匹配

- span 或 page range 对齐

这样后面你可以先做低成本 eval，再逐渐做严。

---

## 8. 第四层：Citation / Grounding Eval

## 8.1 为什么这是你这个系统里最重要的一层

因为你不是做普通聊天问答，而是做 research workflow。
你真正想要的是：

- 论文卡片里方法/结果有证据
- reviewer 能检查 unsupported claims
- 最终 report draft 的 citation 能回指到具体 source/chunk/span

这一步如果做不好，整个 workflow 的可信度会掉得很厉害。

RAGAs 里的 faithfulness、ARES 里的 answer faithfulness，其实都在朝这个方向走；而 PaperTrail 和 FactReview 更贴你这个场景，它们都强调 claim-evidence grounding，而不是只给一个“答案像不像对”。([aclanthology.org](https://aclanthology.org/2024.eacl-demo.16/?utm_source=chatgpt.com "RAGAs: Automated Evaluation of Retrieval Augmented ..."))

---

## 8.2 推荐指标

### Citation Reachability Rate

最终回答或中间 artifact 里的 citation，能否回指到具体 paper/chunk/source。

### Supported Claim Rate

输出里的 claims 中，有多少能被已检索到的 evidence 支撑。

### Unsupported Claim Rate

输出里的 claims 中，有多少找不到支撑证据。

### Coverage Gap Count

某个 sub-question / section 下，系统明显缺证据或缺论文的地方有多少。

这些也正是你前面在 Phase 2 里已经写下来的第四层指标。

---

## 8.3 这一层和 reviewer 的关系

这里要非常明确：

**citation correctness 不等于 retrieval correctness。**

所以这层最好不是只看 `RagResult`，而是联合看：

```text
RagResult
+ PaperCard
+ ReviewFeedback
```

也就是说：

- Retrieval 告诉你“证据有没有被找回来”
- Reviewer 告诉你“最终 claim 有没有真正被 evidence 支撑”

这也正是你前面强调的：citation correctness 最终要靠 RAG + reviewer 联合完成。

---

## 9. Eval Case 怎么设计

这一层是模块 7 能不能落地的关键。

建议正式引入：

```text
RagEvalCase
- case_id
- query
- sub_questions[]
- gold_papers[]
- gold_evidence[]
- gold_claim_support[]
- filters
- notes
```

你前面已经把这个 schema 想出来了，这一步就是把它真正用起来。

### 为什么这个 case 设计很关键

因为你后面不只是要跑一个策略，而是要比较：

- `hybrid_basic`
- `hierarchical`
- `multistage`
- `hierarchical_multistage`

你前面也明确写了模块 7 的目标就是回答：哪种策略更能召回相关论文、排序更稳定、命中支持 citation 的证据块、并更适合后续 reviewer。

所以一个 case 要能支持“同题多跑”。

---

## 10. 模块 7 的执行流程

## 10.1 单 case 执行流程

```text
RagEvalCase
    ↓
run retrieval strategy
    ↓
collect Initial Candidate Pool
    ↓
collect Top-K PaperCandidate
    ↓
collect EvidenceChunk[]
    ↓
collect RagResult
    ↓
compute retrieval metrics
compute ranking metrics
compute evidence metrics
compute citation/grounding metrics
    ↓
EvalCaseResult
```

## 10.2 多策略比较流程

```text
RagEvalCase Set
      ↓
run strategy A / B / C / D
      ↓
collect metrics per strategy
      ↓
compare paper recall
compare ranking quality
compare evidence hit
compare citation support
      ↓
RagEvalReport
```

你前面已经把这个 compare & report 主线写出来了，这里只是把它和模块 1–6 真正对齐。

---

## 11. 推荐工程结构

```text
src/eval/rag/
  runner.py
  metrics.py
  matchers.py
  report.py
  cases/
    phase2_smoke.jsonl
    phase2_regression.jsonl
```

### 各文件职责

`runner.py`

- 驱动不同策略执行
- 统一收集中间 artifact

`metrics.py`

- 计算 retrieval / ranking / evidence / grounding 指标

`matchers.py`

- 负责 gold vs predicted 的匹配逻辑
- 例如 paper title matching、evidence text hint matching

`report.py`

- 生成比较报告
- 输出 per-strategy summary 和 bad cases

你前面 Phase 2 的目录建议里已经把 `eval/rag/runner.py metrics.py report.py cases/` 明确出来了，这个结构可以直接沿用。

---

## 12. 模块 7 的流图

### 总体流图

```text
RagEvalCase Set
      ↓
run strategy
  ├─ paper retrieval
  ├─ dedup + rerank
  ├─ evidence retrieval
  └─ RagResult build
      ↓
collect artifacts
  ├─ candidate papers
  ├─ rerank output
  ├─ evidence chunks
  └─ RagResult
      ↓
compute metrics
  ├─ retrieval
  ├─ ranking
  ├─ evidence
  └─ citation / grounding
      ↓
RagEvalReport
```

### 和后续 Phase 3 / 4 的衔接流图

```text
RagEvalReport
    ├─ informs retriever tuning
    ├─ informs reviewer threshold
    ├─ supports regression tests
    └─ supports strategy comparison
```

也就是说，模块 7 不是 Phase 2 的尾巴，而是后面 reviewer、trace、internal eval 的基础。

---

## 13. 设计参考

### 核心参考

1. **RAGAs**
   适合支撑 reference-free、component-aware 的 RAG 评估思路。([aclanthology.org](https://aclanthology.org/2024.eacl-demo.16/?utm_source=chatgpt.com "RAGAs: Automated Evaluation of Retrieval Augmented ..."))
2. **ARES**
   适合支撑 automated evaluation，尤其是 context relevance / answer faithfulness / answer relevance 三分法。([arXiv](https://arxiv.org/abs/2311.09476?utm_source=chatgpt.com "ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems"))
3. **Evaluation of Retrieval-Augmented Generation: A Survey**
   适合支撑“为什么要分层评估 retrieval、generation 与整体系统”。([arXiv](https://arxiv.org/abs/2405.07437?utm_source=chatgpt.com "Evaluation of Retrieval-Augmented Generation: A Survey"))

### 对你这个 research workflow 更贴的参考

4. **PaperTrail**
   适合支撑 claim-evidence interface，而不仅是 passage citation。([arxiv.org](https://arxiv.org/abs/2602.21045?utm_source=chatgpt.com))
5. **FactReview**
   适合支撑 evidence-grounded review / verification 方向。([arxiv.org](https://arxiv.org/abs/2604.04074?utm_source=chatgpt.com))

---

## 14. 模块 7 的交付物

模块 7 做完，应该明确交付：

- `RagEvalCase`
- `runner.py`
- `metrics.py`
- `RagEvalReport`
- 四层核心指标：

  - retrieval
  - ranking
  - evidence
  - citation / grounding

以及一个正式接口：

- `/evals/rag/run`

这也和你前面 Phase 2 的 API 设计是一致的。

---

## 15. 最后收敛一句话

如果把模块 1–6 概括成“把 research RAG 做出来”，
那模块 7 做的就是：

**证明这套 RAG 到底哪一层变好了、哪一层还不行。**

而且在你这个系统里，模块 7 的价值比普通聊天 RAG 更高，因为你后面还要把它接到：

- `extract_cards`
- `review`
- `citation grounding`
- `write_report`
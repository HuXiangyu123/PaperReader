# 模块 6：Chunk-level Evidence Retrieval + RagResult Builder

## 1. 这个模块解决什么问题

模块 5 结束以后，你已经有了一个去重并排好序的 `Top-K PaperCandidate` 列表。
但这还不够，因为后面的 `extract_cards`、`reviewer`、`citation grounding`、`report writing` 真正需要的不是“论文名字”，而是：

- 这篇论文里哪一段在讲方法
- 哪一段在讲实验设置
- 哪一段在讲结果
- 哪一段能支持某个具体 claim
- 哪一段更适合作为 citation evidence

也就是说，模块 6 的核心不是再做一次“找论文”，而是做：

**evidence localization（证据定位）**

这个问题在 scholarly QA / scientific RAG 里很关键。PaperQA 的核心特点之一就是：不仅跨全文检索 scientific articles，还会评估来源和 passage 的相关性，再用这些 passage 去回答问题。([ar5iv](https://ar5iv.labs.arxiv.org/html/2312.07559?utm_source=chatgpt.com "PaperQA: Retrieval-Augmented Generative Agent for ... - ar5iv"))
PaperTrail 更进一步，直接把 scholarly QA 的问题定义成“claim-evidence mapping”：它指出普通 source citation 的粒度太粗，不足以支持严谨验证，因此需要把回答和文档都拆成 claims 和 evidence 来建立映射。([arXiv](https://arxiv.org/abs/2602.21045?utm_source=chatgpt.com "PaperTrail: A Claim-Evidence Interface for Grounding Provenance in LLM-based Scholarly Q&A"))
FactReview 也说明了类似方向：review 不是只读论文表面叙述，而是要做 evidence-grounded claim verification。([arXiv](https://arxiv.org/abs/2604.04074?utm_source=chatgpt.com "FactReview: Evidence-Grounded Reviews with Literature ..."))

所以模块 6 的目标可以一句话概括成：

**把“论文候选”变成“可验证、可抽取、可写作”的证据对象。**

---

## 2. 这个模块的输入和输出

## 输入

模块 6 的输入主要有三类：

### 第一类：`Top-K PaperCandidate`

来自模块 5，表示已经确认值得深入看的论文候选。

### 第二类：query / sub-questions

因为 evidence retrieval 不是只围绕总 query，还经常要围绕具体子问题。
例如：

- “how they retrieve papers”
- “how they verify citations”
- “what datasets are used”

### 第三类：fine chunks

这些 fine chunks 来自模块 2 和模块 3，已经有：

- `canonical_id`
- `section`
- `page range`
- `parent_chunk_id`
- text
- vector representation

## 输出

模块 6 结束后，建议输出两个层次的对象：

### `EvidenceChunk[]`

表示检索到的具体证据块。

### `RagResult`

表示这次检索任务的正式中间产物，后续直接喂给 `extract_cards`、`reviewer`、`write_report`。你前面设计里也已经明确要求 `RagResult` 不是字符串，而是结构化 artifact。

---

## 3. 这个模块的总体结构

我建议把模块 6 拆成 5 个子步骤：

### 3.1 Scope Restriction

只在选中的论文内部做 evidence retrieval，而不是全库再跑一次。

### 3.2 Fine Chunk Recall

针对 query / sub-question，在这些论文内部检索 fine chunks。

### 3.3 Evidence Rerank / Filtering

对 chunk 再做一次精排或筛选，让最终 evidence 更贴问题。

### 3.4 Evidence Typing

给 evidence 标注更适合的语义角色，比如：

- method
- result
- limitation
- background
- claim\_support

### 3.5 RagResult Build

把论文候选、证据块、检索 trace、dedup/rerank 日志、coverage notes 组装成结构化结果。

---

## 4. Scope Restriction：为什么一定先“收缩范围”

这一层非常关键。
因为模块 6 不是再做一次全库开放检索，而是：

**在模块 5 已经确认的候选论文内部，找最 relevant 的证据块。**

这样做有三个直接好处：

第一，降低噪声。
你已经通过 paper-level retrieval 把大量无关论文排掉了，现在证据检索只在相关论文内部进行，命中率会更高。

第二，降低计算成本。
fine chunk 数量远大于 paper 数量，如果不先缩范围，evidence retrieval 成本和噪声都会上升。

第三，更符合 review / citation 逻辑。
reviewer 后面关心的是“这篇已选论文里有没有支持你说法的证据”，而不是“全库还有没有别的碎片”。PaperTrail 也强调 scholarly QA 的问题在于需要更细粒度的 provenance，而不是只给粗来源引用。([arXiv](https://arxiv.org/abs/2602.21045?utm_source=chatgpt.com "PaperTrail: A Claim-Evidence Interface for Grounding Provenance in LLM-based Scholarly Q&A"))

所以这一步通常做成：

```text
Top-K PaperCandidate
      ↓
collect canonical_id/doc_id
      ↓
restrict fine chunk search scope
      ↓
evidence retrieval only within selected papers
```

---

## 5. Fine Chunk Recall：真正去找证据块

## 5.1 检索对象是什么

这里的主对象不再是论文或 coarse chunk，而是：

- `FineChunk`
- 但必须带着它的 `canonical_id / parent_chunk_id / section / page` 一起走

原因很简单：
后面 reviewer 和 citation grounding 不只关心这段话内容对不对，还关心：

- 它来自哪篇论文
- 在哪一页
- 属于哪个 section
- 是否真能回指到 source

SF-RAG 的描述就很贴你这里的逻辑：很多 scientific RAG 会把论文 flatten 成无结构 chunks，结果造成 evidence misalignment；它强调的是在 fixed token budget 下更准确地分配证据。([arXiv](https://arxiv.org/html/2602.13647v2?utm_source=chatgpt.com "SF-RAG: Structure-Fidelity Retrieval-Augmented ..."))

---

## 5.2 Query 怎么组织

这里建议 evidence retrieval 不只跑一个 query。
最合理的是三种 query 并行：

### 总 query

例如：

- “recent multimodal agents for scientific literature review”

### 子问题 query

例如：

- “how they retrieve papers”
- “how they verify citations”

### claim-oriented query（如果后面 reviewer 已经提出具体问题）

例如：

- “evidence that the method uses citation graph”
- “evidence that evaluation includes ScholarQA benchmark”

这样你最后得到的 `EvidenceChunk` 才能带上：

- 是为哪个子问题找的
- 是为哪个 claim 找的

这和你前面 `RagResult` / `EvidenceChunk` 设计里预留的 `sub_question_id` 是一致的。

---

## 5.3 Recall 用什么方式

这一层建议以 **dense retrieval on fine chunks** 为主，必要时可叠加轻量 lexical matching。

原因是 fine chunk 检索的目标已经不是“宽泛找主题”，而是“精确命中局部证据”。
ChunkRAG 这类工作正是在解决这个问题：它指出 document-level 方法往往难以过滤掉 loosely related 信息，所以需要更细粒度的 chunk-level filtering。([arXiv](https://arxiv.org/html/2410.19572v3?utm_source=chatgpt.com "Novel LLM-Chunk Filtering Method for RAG Systems"))

推荐结构可以是：

```text
query / sub-question / claim
        ↓
fine dense retrieval
        ↓
optional lexical boost
        ↓
candidate evidence chunks
```

---

## 6. Evidence Rerank / Filtering：为什么 chunk 也要再排一次

模块 5 已经做过 paper rerank，但那不代表 chunk 级别的顺序已经可信。

因为在同一篇论文内部，可能有很多 fine chunk 都和 query “有点像”，比如：

- 方法概述段
- 结果分析段
- 讨论段
- 相关工作段

如果不再对 chunk 做精排，后面很容易出现 evidence mismatch：

- 你要方法证据，结果召回到 related work
- 你要实验结果，结果召回到背景介绍
- 你要 citation support，结果召回到不支持 claim 的相邻段落

SF-RAG 用 “retrieval fragmentation” 和 “evidence misalignment” 这两个词描述的，其实就是这类问题。([arXiv](https://arxiv.org/html/2602.13647v2?utm_source=chatgpt.com "SF-RAG: Structure-Fidelity Retrieval-Augmented ..."))

所以 chunk 阶段建议加一个轻量 rerank / filter：

### 可行做法

- cross-encoder rerank `(query, fine_chunk_text)`
- 小模型 relevance classifier
- 基于 section / support type 的启发式过滤

### 推荐策略

如果算力允许，就做：
**dense recall → chunk rerank**
这样 chunk 级 evidence 会稳很多。

---

## 7. Evidence Typing：为什么要给 evidence 加语义角色

这一层不是必须用模型单独做复杂分类，但从 artifact 设计上，最好提前给 evidence 留出 `support_type` 字段。

你前面自己的 schema 里其实已经这么设计了：

```text
EvidenceChunk
- chunk_id
- paper_id
- section
- page_range
- text
- score
- support_type
```

support\_type 可以先设计成：

- `background`
- `method`
- `result`
- `limitation`
- `claim_support`
- `unknown`

### 为什么这个字段很重要

因为后面的模块用法完全不同：

- `extract_cards` 更关心 method / result / limitation
- reviewer 更关心 claim\_support
- write\_report 可能会优先用 background + comparison-relevant evidence

PaperTrail 之所以强调 claim-evidence interface，就是因为只给 passage 不够，系统还需要知道“这段话在支持什么”。([arXiv](https://arxiv.org/abs/2602.21045?utm_source=chatgpt.com "PaperTrail: A Claim-Evidence Interface for Grounding Provenance in LLM-based Scholarly Q&A"))
FactReview 也在往同一个方向走：review 不是只给评论，而是要把 claim 和 evidence 对齐。([arXiv](https://arxiv.org/abs/2604.04074?utm_source=chatgpt.com "FactReview: Evidence-Grounded Reviews with Literature ..."))

---

## 8. RagResult Builder：为什么 `RagResult` 不能是一段字符串

这是模块 6 里最重要的工程结论。

如果 evidence retrieval 之后你只是返回：

“找到了这些段落，下面是拼接文本……”

那后面的很多模块都会非常痛苦：

- `extract_cards` 还得从大段字符串里再解析
- reviewer 不知道 evidence 对应哪个 sub-question
- eval 无法定位是哪个 retrieval path 出的问题
- workspace 面板也不能把 evidence 作为 artifact 展示

所以 `RagResult` 必须是正式 artifact，而不是聊天上下文。你前面的 Phase 2 设计也已经明确写了：这个阶段要做结构化 `RagResult`，而不是字符串拼接。

### 建议的 `RagResult` 组成

```text
RagResult
- query
- rag_strategy
- sub_question_id(optional)
- paper_candidates[]
- evidence_chunks[]
- retrieval_trace[]
- dedup_log[]
- rerank_log[]
- coverage_notes[]
```

### 这里面每一项的作用

`paper_candidates[]`

- 表示这次 evidence 是建立在哪批候选论文上的

`evidence_chunks[]`

- 表示最终找到的证据块

`retrieval_trace[]`

- 记录 chunk retrieval 的 query / path / top\_k / filters

`dedup_log[]`

- 从模块 5 继承过来，让后续 reviewer 可追踪来源归并

`rerank_log[]`

- 包括 paper rerank 和 chunk rerank 的关键结果

`coverage_notes[]`

- 标注有哪些 sub-question evidence 不足，方便 Phase 3 reviewer 做 coverage gap 检查

这和你前面写的 reviewer 主线正好能接上：如果没有结构化 `RagResult`、evidence chunks、retrieval trace、dedup / rerank log，reviewer 基本没法做。

---

## 9. 推荐工程结构

```text
src/corpus/search/
  retrievers/
    chunk_retriever.py
  reranker.py
  evidence_filter.py
  evidence_typer.py
  result_builder.py
```

### 各文件职责

`chunk_retriever.py`

- 在 selected papers 内做 fine chunk retrieval
- 支持 query / sub-question / claim scope

`reranker.py`

- chunk-level rerank
- 和 paper rerank 共用底层也可以，但逻辑分开

`evidence_filter.py`

- top\_k 截断
- 按 section 或 support constraints 过滤

`evidence_typer.py`

- method/result/claim\_support 等轻量标注

`result_builder.py`

- 构建正式 `RagResult`

---

## 10. 模块 6 的流图

### 总体流图

```text
Top-K PaperCandidate
        ↓
Scope Restriction
(only selected papers)
        ↓
Fine Chunk Recall
(query / sub-question / claim)
        ↓
Chunk Rerank / Filtering
        ↓
Evidence Typing
(method / result / limitation / claim_support)
        ↓
EvidenceChunk[]
        ↓
RagResult Builder
        ↓
Structured RagResult
```

### 和后续 workflow 的衔接流图

```text
Structured RagResult
    ├─ extract_cards
    │    → PaperCard[]
    ├─ review
    │    → ReviewFeedback
    └─ write_report
         → grounded draft with evidence refs
```

### 更细一点的 query-to-evidence 流图

```text
query + sub_questions
        ↓
for each selected paper:
    retrieve fine chunks
        ↓
merge evidence across papers
        ↓
rerank evidence globally / per sub-question
        ↓
attach section/page/support_type
        ↓
EvidenceChunk[]
```

---

## 11. 设计参考

### 论文 / 系统参考

1. **PaperQA**
   适合支撑“在 scientific full-text 上做 passage-level retrieval，再基于 passages 回答”的总体路线。([ar5iv](https://ar5iv.labs.arxiv.org/html/2312.07559?utm_source=chatgpt.com "PaperQA: Retrieval-Augmented Generative Agent for ... - ar5iv"))
2. **PaperTrail: A Claim-Evidence Interface for Grounding Provenance in LLM-based Scholarly Q&A**
   非常适合支撑你这里的 `EvidenceChunk` 和 claim-evidence 对齐设计。它明确指出普通 citation 粒度太粗，需要离散 claims 和 evidence 的映射。([arXiv](https://arxiv.org/abs/2602.21045?utm_source=chatgpt.com "PaperTrail: A Claim-Evidence Interface for Grounding Provenance in LLM-based Scholarly Q&A"))
3. **FactReview: Evidence-Grounded Reviews with Literature Positioning and Execution-Based Claim Verification**
   适合支撑“evidence retrieval 不是只为回答服务，还要为 review / verification 服务”。([arXiv](https://arxiv.org/abs/2604.04074?utm_source=chatgpt.com "FactReview: Evidence-Grounded Reviews with Literature ..."))
4. **SF-RAG: Structure-Fidelity RAG**
   适合支撑为什么要减少 retrieval fragmentation 和 evidence misalignment。([arXiv](https://arxiv.org/html/2602.13647v2?utm_source=chatgpt.com "SF-RAG: Structure-Fidelity Retrieval-Augmented ..."))
5. **ChunkRAG / chunk-level filtering**
   适合支撑为什么 chunk retrieval 后还要再做 filtering。([arXiv](https://arxiv.org/html/2410.19572v3?utm_source=chatgpt.com "Novel LLM-Chunk Filtering Method for RAG Systems"))

### 博客 / 官方文档参考

1. **Haystack – AutoMergingRetriever**
   对“leaf evidence 命中后保留父级上下文”这个工程思路很有帮助，尤其在 scholarly long-doc 里。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/automergingretriever))
2. **Sentence Transformers – Retrieve & Re-Rank**
   可以直接借它的 retrieve-then-rerank 逻辑到 fine chunk evidence retrieval。([sbert.net](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html?utm_source=chatgpt.com))

---

## 12. 模块 6 的交付物

模块 6 做完，应该明确交付：

- `chunk_retriever.py`
- chunk-level rerank / filter
- `EvidenceChunk[]`
- `RagResult`
- `retrieval_trace`
- `coverage_notes`

到这一步，RAG 主链其实已经基本闭合了：

- 模块 4：先找论文
- 模块 5：去重 + 排序
- 模块 6：找证据 + 结构化结果

也正因为这样，模块 7 才能真正做成独立的 **RAG Eval**，评估：

- 论文召回
- 排序质量
- 证据命中
- citation / claim support

下一条如果继续，我就按同样格式讲 **模块 7：RAG Eval**。
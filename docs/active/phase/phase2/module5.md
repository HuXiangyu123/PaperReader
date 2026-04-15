好，继续讲 **模块 5：Dedup + Rerank**。
如果把模块 4 概括成“先尽量找全”，那模块 5 就是“再尽量排准”。这一步在现代 RAG 里很常见：先用较快的检索器做高召回候选，再用更强但更贵的 reranker 精排。Pinecone 的两阶段检索文章就是这个典型表述；Sentence Transformers 的 `Retrieve & Re-Rank` 文档也明确把 bi-encoder 召回和 cross-encoder 重排分成两段。([pinecone.io](https://www.pinecone.io/learn/series/rag/rerankers/?utm_source=chatgpt.com "Rerankers and Two-Stage Retrieval"))

---

# 模块 5：Dedup + Rerank

## 1. 这个模块解决什么问题

模块 4 结束后，你拿到的是一个 **Initial Paper Candidate Pool**。这个候选池通常会有三类现象：

同一篇论文会因为不同来源被重复召回，比如本地 PDF、上传 PDF、arXiv 页面、conference 版本同时出现；
同一篇论文也可能因为不同子问题、多路 hybrid recall 被重复命中；
而且当前排序还只是 recall 分数，不足以直接作为最终论文顺序。你前面的 Phase 2 设计其实已经把这一点写得很明确：模块 4 之后还要做 canonical dedup，再做 paper rerank，最后才得到 Top-K `PaperCandidate`。

所以模块 5 的目标非常清楚：

**把“多路粗召回论文池”收束成“去重后的高质量 Top-K 论文候选”。** 
这里要分成两个子目标：

- **Dedup**：解决论文身份和版本重复
- **Rerank**：解决相关性排序不稳定

---

## 2. 为什么 Dedup 和 Rerank 要放在一起讲

因为这两步虽然逻辑不同，但在工程上是前后紧密耦合的。

如果你先不 dedup，直接 rerank，那么 reranker 会把同一篇论文的多个来源版本反复打高分，最终占满 Top-K；
如果你只 dedup 不 rerank，那最终候选的排序仍然主要受 recall 阶段影响，通常不够稳。
很多两阶段 retrieval 实践都是先把候选集合整理干净，再把有限预算花在精排上。Pinecone 的两阶段检索文档和多阶段检索文章都在强调：前段追求高召回，后段追求高精度。([pinecone.io](https://www.pinecone.io/learn/series/rag/rerankers/?utm_source=chatgpt.com "Rerankers and Two-Stage Retrieval"))

所以模块 5 的合理顺序就是：

```text
Initial Candidate Pool
        ↓
Canonical Dedup
        ↓
Rerank
        ↓
Top-K PaperCandidate
```

---

## 3. Dedup：要解决的不是“文件重复”，而是“论文重复”

这一步不要把它理解成简单文件去重。
你这里真正要做的是 **paper-level canonical dedup**。

也就是说，你需要把这些来源统一映射到同一个 canonical paper：

- 本地目录 PDF
- 用户上传 PDF
- 在线 arXiv
- conference 版
- journal 扩展版

你之前在模块 1 已经做过 canonicalization，所以这里不是重新猜身份，而是利用已有的 `canonical_id` 做候选合并。

### 3.1 Dedup 的输入对象

模块 4 输出的每个 candidate 至少应带这些信息：

```text
MergedCandidate
- doc_id
- canonical_id(optional)
- source_ref
- matched_queries[]
- matched_paths[]
- raw_scores
- recall_evidence_refs
```

### 3.2 Dedup 的核心动作

Dedup 不是把重复候选简单删掉，而是做 **聚合**。
对于同一个 canonical paper，建议聚合：

- 所有来源 `source_refs`
- 所有匹配到的 query / sub-question
- 所有 recall path（keyword / dense）
- 各路原始分数
- 命中的 coarse chunk refs

也就是说，dedup 后的对象更像一个“论文聚合候选”：

```text
DedupedPaperCandidate
- canonical_id
- merged_doc_ids[]
- source_refs[]
- matched_queries[]
- matched_paths[]
- aggregated_recall_signals
- representative_texts
```

### 3.3 版本关系怎么保留

这里建议：

- **同 canonical paper 的多来源版本合并**
- 但 **source/version 信息保留在** **`source_refs[]`**  里
- conference/journal 这种“正式版关系”不要丢

因为后面 reviewer 还要做 citation reachability，用户也可能需要知道当前引用的是哪一版。你前面也已经明确要求：要区分 arXiv / conference / journal 版本，并保留 source refs 和 version info。

---

## 4. Rerank：为什么 recall 之后还不够

Recall 阶段的目标是“别漏太多”，所以它天然更偏高召回。
但高召回的代价就是候选里会混入：

- 主题相关但不够核心的论文
- 只在某个局部 chunk 上相似的论文
- 术语碰巧命中的论文
- 同一方法路线里边缘相关的论文

这时候就需要 rerank 来解决“谁更值得进入 Top-K”。

Sentence Transformers 的官方文档把这个问题讲得很清楚：bi-encoder 适合高效召回，Cross-Encoder 不适合全库检索，但非常适合对少量候选做重排。([sbert.net](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html?utm_source=chatgpt.com "Retrieve & Re-Rank Pipeline"))
Pinecone 的 Rerank 资料也直接把 reranker 描述为“在少量延迟成本下显著提高检索结果质量”的方法。([pinecone.io](https://www.pinecone.io/learn/refine-with-rerank/?utm_source=chatgpt.com "Refine Retrieval Quality with Pinecone Rerank"))

---

## 5. Rerank 具体怎么做

## 5.1 Rerank 的输入

paper rerank 阶段，不建议直接只喂 title。
更合理的输入是：

```text
query
+ title
+ abstract
+ top matched coarse chunks
+ optional metadata summary
```

### 为什么这样设计

因为论文相关性不只体现在标题。
有时标题很泛，但 abstract 和 method overview 很强；
有时 abstract 很泛，但某个 coarse chunk 明确击中你的 sub-question。

所以最稳的 paper rerank 输入通常是：

- 标题
- 摘要
- 若干代表性 coarse chunk

而不是只拿一个字段。

---

## 5.2 推荐的 rerank 模型形态

在工程上，最常见的是：

### 方案 A：Cross-Encoder Reranker

输入 `(query, candidate_text)` 成对打分。
这是最经典、也最稳的方案。Sentence Transformers 官方把 cross-encoder 作为 Retrieve & Re-Rank pipeline 的第二阶段标准做法。([sbert.net](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html?utm_source=chatgpt.com "Retrieve & Re-Rank Pipeline"))

### 方案 B：LLM-as-reranker

让大模型做 pairwise/listwise relevance 判断。
这个更灵活，但成本更高，稳定性也更依赖 prompt。
对你现在这一步，我建议暂时作为后续增强，不要一开始就主打。

### 方案 C：线性/启发式重排

对 recall 分数做融合后直接排序。
这只能作为 baseline，不能替代真正的 reranker。

### 我的建议

模块 5 默认先采用：

**Cross-Encoder / neural reranker 作为主方案**

因为：

- 候选池已经被缩小
- 相关性判断比 recall 更精细
- 成本可控
- 也是社区最成熟的做法。([sbert.net](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html?utm_source=chatgpt.com "Retrieve & Re-Rank Pipeline"))

---

## 5.3 先融合还是先重排

这里推荐顺序是：

### 第一步：候选聚合

先把 keyword recall 和 dense recall 的结果 merge 到一起。

### 第二步：轻量融合分数

可以先做一个 recall-stage fusion，帮助缩小到 rerank 预算范围内。

### 第三步：rerank

对保留下来的候选论文跑更强的重排模型。

Elastic 的混合检索博客对 **RRF（Reciprocal Rank Fusion）**  和线性组合作为融合方式讲得很清楚：它们适合把 lexical 与 dense 的召回结果先合并到一个统一顺序里。([elastic.co](https://www.elastic.co/search-labs/blog/hybrid-search-multi-stage-retrieval-esql)) ([elastic.co](https://www.elastic.co/search-labs/blog/hybrid-search-elasticsearch))
所以模块 5 的前半段可以看成：

```text
keyword recall + dense recall
        ↓
fusion (e.g. RRF / weighted fusion)
        ↓
deduped candidate pool
        ↓
cross-encoder rerank
```

---

## 6. 一个推荐的 Dedup + Rerank 执行流程

```text
Initial Candidate Pool
    ├─ candidate from keyword recall
    ├─ candidate from dense recall
    └─ candidate from multiple sub-questions
          ↓
Canonical Dedup
    ├─ merge same canonical_id
    ├─ collect source refs
    ├─ merge matched queries
    └─ keep version info
          ↓
Recall Fusion
    ├─ RRF / weighted fusion
    └─ budget trim (top M)
          ↓
Paper Rerank
    ├─ query + title
    ├─ query + abstract
    └─ query + key coarse chunks
          ↓
Top-K PaperCandidate
```

### 这里的 `Top M`

表示进入 rerank 的预算池。
因为 cross-encoder 比 recall 更贵，不应该对全部候选跑。

---

## 7. 结果对象怎么设计

模块 5 结束后，输出应该升级成你前面定义的正式对象：

```text
PaperCandidate
- paper_id
- canonical_id
- title
- authors
- year
- venue
- source_refs[]
- retrieval_scores
- matched_queries[]
- why_retrieved
```

这里建议把 `retrieval_scores` 明确拆开：

```text
ScoreBreakdown
- lexical
- dense
- fusion
- rerank
- final
```

这样：

- reviewer 能看来源
- eval 能做诊断
- 前端以后也能展示“为什么它排在前面”

你前面 Phase 2 的 schema 设计里，本来也已经给 `PaperCandidate` 预留了 `scores` 和 `why_retrieved`。

---

## 8. 模块 5 和后面模块怎么衔接

模块 5 结束以后，后面的系统就不再处理“杂乱候选池”，而是处理：

**去重且排好序的论文候选列表**

这一步直接给三个模块喂数据：

### 给 `select_papers`

做阈值/数量控制，筛掉尾部论文

### 给 `extract_cards`

按 `Top-K PaperCandidate` 生成 `PaperCard`

### 给模块 6（chunk-level evidence retrieval）

在这些已确认高相关的论文内部做 fine chunk 检索

所以模块 5 是 paper-level retrieval 和 evidence retrieval 的分水岭。

---

## 9. 推荐工程结构

```text
src/corpus/search/
  deduper.py
  fusion.py
  reranker.py
  candidate_builder.py
```

### 各文件职责

`deduper.py`

- canonical merge
- 聚合同一论文的多来源结果

`fusion.py`

- lexical / dense 结果融合
- RRF / weighted fusion

`reranker.py`

- cross-encoder / neural reranker 调用
- rerank budget 控制

`candidate_builder.py`

- 构建最终 `PaperCandidate`
- 填充 `scores`、`matched_queries`、`why_retrieved`

---

## 10. 模块 5 的流图

### 总体流图

```text
Initial Paper Candidate Pool
        ↓
Canonical Dedup
  ├─ merge same paper across sources
  ├─ preserve source/version info
  └─ aggregate recall signals
        ↓
Fusion
  ├─ combine keyword and dense signals
  └─ form rerank budget pool
        ↓
Paper Rerank
  ├─ query + title
  ├─ query + abstract
  └─ query + key coarse chunks
        ↓
Top-K PaperCandidate
```

### 和模块 6 的衔接流图

```text
Top-K PaperCandidate
        ↓
restrict search scope to selected papers
        ↓
fine chunk evidence retrieval
        ↓
EvidenceChunk[]
```

---

## 11. 设计参考

### 论文 /方法参考

1. **Sentence Transformers – Retrieve & Re-Rank Pipeline**
   这是你模块 5 最直接的工程参考。它明确采用 bi-encoder 做第一阶段召回，再用 Cross-Encoder 对候选精排。([sbert.net](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html?utm_source=chatgpt.com "Retrieve & Re-Rank Pipeline"))
2. **Pinecone – Rerankers and Two-Stage Retrieval**
   这篇很适合支撑“先召回、后重排”的两阶段设计。([pinecone.io](https://www.pinecone.io/learn/series/rag/rerankers/?utm_source=chatgpt.com "Rerankers and Two-Stage Retrieval"))
3. **Pinecone – Cascading retrieval**
   适合进一步支撑“逐步提高模型复杂度”的分阶段检索设计。([pinecone.io](https://www.pinecone.io/blog/cascading-retrieval/?utm_source=chatgpt.com "Introducing cascading retrieval: Unifying dense and sparse ..."))
4. **AIRwaves / scientific claim source retrieval paper**
   这类论文说明“dense retrieval + neural reranking”在科研文献匹配场景里是很自然的路线，和你的 paper-level retrieval 非常贴。([arXiv](https://arxiv.org/pdf/2509.19509?utm_source=chatgpt.com "AIRwaves at CheckThat! 2025: Retrieving Scientific ..."))

### 博客 / 官方文档参考

1. **Elastic – Hybrid search and multistage retrieval**
   适合支撑 fusion 阶段为什么会用 RRF 或线性加权。([Elastic](https://www.elastic.co/search-labs/blog/hybrid-search-multi-stage-retrieval-esql?utm_source=chatgpt.com "Hybrid search and multistage retrieval in ES|QL"))
2. **Elastic – Weighted RRF**
   适合做后续增强参考：当你发现不同 recall 路径重要性不一样时，可以从统一权重升级成加权融合。([Elastic](https://www.elastic.co/search-labs/blog/weighted-reciprocal-rank-fusion-rrf?utm_source=chatgpt.com "Weighted reciprocal rank fusion(RRF) in Elasticsearch"))

---

## 12. 模块 5 的交付物

模块 5 做完，应该明确交付：

- `deduper.py`
- `fusion.py`
- `reranker.py`
- `candidate_builder.py`
- `Top-K PaperCandidate`
- `dedup_log`
- `rerank_log`
- `score_breakdown`

到这一步，你的系统已经具备：

**把多路召回的论文池，变成后续 workflow 可以真正依赖的高质量论文候选集。**
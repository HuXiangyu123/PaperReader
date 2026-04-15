好，继续讲 **模块 4：Paper-level Retrieval**。
这一步的任务很明确：**先找对论文，而不是直接找答案。**

你前面已经把 Phase 2 主线定成了：

- `paper-level retrieval`
- `canonical dedup`
- `paper rerank`
- `Top-K PaperCandidate`
- 再进入 `chunk-level evidence retrieval`。

所以模块 4 的目标不是把所有 chunk 一股脑召回给 LLM，而是把 query 先转成一组**高质量候选论文集**，为后面的 `select_papers`、`extract_cards`、`reviewer` 打底。

---

# 模块 4：Paper-level Retrieval

## 1. 这个模块解决什么问题

模块 3 做完以后，你已经有了：

- `DocumentStore`
- `ChunkStore`
- `coarse_vector_index`
- `fine_vector_index`
- `keyword_index`
- `metadata filter layer`

但此时还没有“论文候选集”。
模块 4 就是把这些底层索引真正组合起来，形成：

**query → coarse recall → merge → candidate papers**

这里要特别注意一点：

**论文级检索不是 chunk 级检索的简单放大版。**

因为你要回答的问题其实是：

- 哪些论文和当前 query / sub-question 相关？
- 哪些论文值得进入下一阶段？
- 哪些论文应该进入 reviewer 的覆盖面视野？

这就要求 paper-level retrieval 更关注：

- 召回覆盖面
- 论文主题相关性
- 元数据约束
- 多源合并前的候选丰富度

而不是一开始就去追求最细证据。

Hybrid search 的核心价值在这里非常明显。Elastic 官方对 hybrid search 的描述就很适合作为这一步的理论支撑：hybrid search 结合 lexical 和 semantic retrieval，能同时利用关键词精确匹配和语义匹配能力。([elastic.co](https://www.elastic.co/what-is/hybrid-search))
Haystack 的材料也直接指出，BM25 通常偏 precision，而 embedding retrieval 更偏 recall，把两者结合更合理。([haystack.deepset.ai](https://haystack.deepset.ai/blog/query-expansion))

---

## 2. 这个模块的目标输出

模块 4 结束后，应该输出的是：

```text
InitialPaperCandidates
- query
- sub_question_id(optional)
- candidate_papers[]
- retrieval_trace
```

其中 `candidate_papers[]` 还不是最终排序后的 `Top-K PaperCandidate`，而是：

- 来自多路 recall 的粗候选
- 可能有重复
- 可能排序还不稳定
- 还没经过 canonical merge 和 rerank

也就是说，模块 4 的产物是：

**高召回论文候选池**

不是最终精排结果。

---

## 3. 模块 4 的实现结构

我建议把 paper-level retrieval 拆成 4 个子步骤：

### 3.1 Query Preparation

把用户 query / `SearchPlan` / `SubQuestion` 转成适合论文检索的 retrieval query。

### 3.2 Hybrid Recall

并行跑：

- keyword recall
- dense recall
- metadata filtering

### 3.3 Candidate Merge

把不同召回路的结果合并成候选集。

### 3.4 Trace Build

记录每一条 candidate 来自哪一路 recall，为后面 dedup/rerank/reviewer 做解释基础。

---

## 4. Query Preparation 怎么做

这一层不要想得太复杂，但一定不能直接把原始用户话术裸丢给 retriever。

建议至少做三件事：

### 4.1 主 query

用户的原始研究问题。

例如：

- “recent multimodal agents for scientific literature review”

### 4.2 子问题 query

来自 `SearchPlan` 的 `sub_questions`。

例如：

- “how they retrieve papers”
- “how they verify citations”

### 4.3 过滤约束

来自用户或 planner 的条件：

- years
- sources
- venue
- workspace scope

你前面的 API 设计本来就要求 `/corpus/search` 支持 `query + sub_questions + filters`，所以模块 4 最自然的做法就是按这个结构跑检索。

### 推荐做法

paper-level retrieval 阶段，不一定非要做很重的 query rewrite，但至少要支持：

- 原始 query
- 1～N 个子问题 query
- metadata filter

这样后面的 reviewer 才能知道：
某篇论文是因为“总体 query”命中的，还是因为“特定子问题”命中的。

---

## 5. Hybrid Recall 怎么做

这是模块 4 的核心。

## 5.1 Recall 跑哪些对象

建议 paper-level recall 不直接跑 fine chunks，而是优先跑：

- `title`
- `abstract`
- `coarse chunks`

也就是说，recall 的逻辑对象虽然可能还是 chunk/document 级记录，但语义上是在判断“这篇论文是否相关”。

---

## 5.2 Keyword Recall

关键词检索适合抓这些信号：

- 模型名
- benchmark / dataset 名
- task name
- author / venue / year
- query 里的强术语

推荐匹配字段：

```text
title
abstract
authors
venue
keywords
coarse_chunk_text
```

### 为什么这里 keyword 很重要

因为 paper-level retrieval 阶段，你特别不想漏掉那些“术语强相关但语义模型未必抓得住”的论文。

Elastic 的 hybrid search 文档就强调，lexical search 和 semantic search 是互补而不是互斥。([elastic.co](https://www.elastic.co/what-is/hybrid-search))

---

## 5.3 Dense Recall

dense recall 适合抓这些信号：

- 同义表达
- 描述型 query
- 用户没有精确复述论文术语的情况
- 语义上相近的方法路线

这里建议只在：

- `coarse_vector_index`
- title/abstract embedding

上做 recall。

不要在 paper-level retrieval 阶段直接用 fine chunk dense recall 作为主入口。
因为那会把很多碎片噪声提早带进来。

---

## 5.4 Metadata Filtering

metadata filtering 建议直接嵌进 recall，而不是最后才补。

例如：

- 先过滤 `workspace_id`
- 再过滤 `source_type`
- 再过滤 `year range`

这样做的好处是：

- 减少无效候选
- 降低后面 merge/rerank 压力
- 更贴近用户意图

Qdrant 官方把 filtering 作为向量检索的核心组成，就是这个逻辑。([qdrant.tech](https://qdrant.tech/documentation/search/filtering/))

---

## 5.5 一个典型 paper recall 结构

```text
SearchPlan / Query
    ├─ main query
    ├─ sub-question queries
    └─ metadata filters
          ↓
   ┌────────────────────────────┐
   │ keyword recall             │
   │ title / abstract / coarse  │
   └────────────────────────────┘
          +
   ┌────────────────────────────┐
   │ dense recall               │
   │ title / abstract / coarse  │
   └────────────────────────────┘
          +
   ┌────────────────────────────┐
   │ metadata filters           │
   │ year / source / workspace  │
   └────────────────────────────┘
          ↓
   merged paper candidates
```

---

## 6. Candidate Merge 怎么做

Recall 跑完后，你拿到的还只是“多路命中的候选项”，此时通常有这些情况：

- keyword 命中的论文 dense 没命中
- dense 命中的论文 lexical 没命中
- 同一论文的不同 source/doc/chunk 重复出现
- 不同 sub-question 命中了不同论文

所以这一步的目标不是排序，而是：

**把不同 recall 路径的候选尽量收齐，并附上来源解释。**

### 推荐 merge 输出字段

```text
MergedCandidate
- candidate_id
- doc_id / canonical_id(optional)
- matched_queries[]
- matched_paths[]         # keyword / dense
- raw_scores
- source_refs
- recall_evidence_refs
```

### 为什么先 merge、后 dedup

因为你还没做 canonical merge。
这里先保留“每条候选是怎么来的”，后面模块 5 再做论文级去重和精排。

---

## 7. Trace Build 怎么做

这一步很重要，尤其你后面还要接 reviewer 和 `/evals/rag/run`。

建议在 paper-level retrieval 阶段就开始写 trace：

```text
RetrievalTrace
- query
- sub_question_id
- retrieval_path      # keyword / dense
- target_index        # title / abstract / coarse
- filter_summary
- top_k
- returned_ids[]
```

### 为什么这一步现在就要做

因为后面 reviewer 如果发现 coverage gap，你需要知道：

- 是 query 本身没覆盖到？
- 还是 dense recall 漏了？
- 还是 lexical recall 压根没命中？
- 还是 filter 太紧？

如果模块 4 不记录 trace，模块 7 做 eval 时很难追原因。

你前面的 `RagResult` 里本来就预留了 `retrieval_trace`。

---

## 8. 推荐工程结构

```text
src/corpus/search/
  retrievers/
    paper_retriever.py
    keyword_retriever.py
    dense_retriever.py
    filter_compiler.py
    candidate_merger.py
    trace_builder.py
```

### 各文件职责

`paper_retriever.py`

- paper-level 检索统一入口
- 调度 keyword / dense / filters

`keyword_retriever.py`

- title / abstract / coarse lexical recall

`dense_retriever.py`

- coarse vector recall

`filter_compiler.py`

- 把 API filters 编译成底层 store/index 可执行条件

`candidate_merger.py`

- 融合多路 recall 结果

`trace_builder.py`

- 写 retrieval trace

---

## 9. 和模块 5 的关系

模块 4 结束时，还没有做两件关键事：

### 9.1 没有 canonical dedup

同一论文可能有：

- 本地 PDF
- uploaded PDF
- arXiv 在线版本
- conference/journal 版本

这些要在模块 5 合并。

### 9.2 没有 final rerank

当前排序还只是 recall 分数，不是最终 relevance ranking。
模块 5 才会做：

- canonical dedup
- paper rerank
- 得到最终 `Top-K PaperCandidate`

也就是说：

```text
模块 4：先尽量找全
模块 5：再尽量排准
```

这和 Pinecone 的 two-stage retrieval 讲法是一致的：先高召回，再用 reranker 精排。([pinecone.io](https://www.pinecone.io/learn/series/rag/rerankers/))

---

## 10. 模块 4 的流图

### 总体流图

```text
SearchPlan / Query
      ↓
Query Preparation
  ├─ main query
  ├─ sub-question queries
  └─ filters
      ↓
Hybrid Recall
  ├─ keyword recall on title/abstract/coarse
  ├─ dense recall on coarse vector index
  └─ metadata-aware filtering
      ↓
Candidate Merge
      ↓
Initial Paper Candidate Pool
      ↓
Retrieval Trace
```

### 和后续模块衔接流图

```text
Initial Paper Candidate Pool
        ↓
canonical dedup
        ↓
paper rerank
        ↓
Top-K PaperCandidate
        ↓
chunk-level evidence retrieval
```

---

## 11. 设计参考

### 论文参考

1. **Fan et al.,**  ***A Survey on RAG Meeting LLMs***
   这篇适合做 paper-level retrieval 的总体理论背景，因为它把 RAG 看成模块化系统，而不是单一 dense retrieval。([arxiv.org](https://arxiv.org/abs/2405.06211?utm_source=chatgpt.com))
2. **CHORUS: Zero-shot Hierarchical Retrieval...** 
   这篇虽然更偏层级树结构，但它强调 hierarchical retrieval 保留 high-level context 与 detailed context 的关系，很适合支撑你“先论文级、后证据级”的分层思路。([arxiv.org](https://arxiv.org/html/2505.01485v1))
3. **KohakuRAG**
   这篇也很贴你现在的路子：document → section → paragraph → sentence 的树结构，并通过 query planner + reranking 提升 coverage。([arxiv.org](https://arxiv.org/html/2603.07612v1))

### 博客 / 官方文档参考

1. **Haystack – Query Expansion**
   它明确指出 BM25 偏 precision、embedding retrieval 偏 recall，这个判断非常适合解释为什么 paper-level retrieval 要做 hybrid。([haystack.deepset.ai](https://haystack.deepset.ai/blog/query-expansion))
2. **Elastic – Hybrid Search**
   适合支撑 lexical + semantic 组合检索。([elastic.co](https://www.elastic.co/what-is/hybrid-search))
3. **Haystack – Retrievers**
   适合支撑 BM25、embedding、hybrid retrievers 并行存在的工程视角。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/retrievers))

---

## 12. 模块 4 的交付物

模块 4 做完，应该明确交付：

- `paper_retriever.py`
- `keyword_retriever.py`
- `dense_retriever.py`
- `filter_compiler.py`
- `candidate_merger.py`
- `retrieval_trace`

以及一个正式的中间结果：

- `Initial Paper Candidate Pool`

到这一步，你的系统就已经具备：

**根据 query 先找出一批“可能相关的论文”，但还没完成最终去重和排序。**
好，直接进 **模块 2：Chunking（Coarse / Fine 双层切块）** 。

这一步是整个 RAG 里最容易被低估、但对效果影响非常大的环节。你前面已经把 Phase 2 的主链定成了：

**先做 paper-level retrieval，再做 chunk-level evidence retrieval**，也就是典型的 **hierarchical retrieval**。在这种设计下，chunking 绝对不能再是“随便按 500 token 切一下”，而要服务于两件不同的事：

- **粗粒度 chunk（coarse chunk）** ：帮助先找对论文
- **细粒度 chunk（fine chunk）** ：帮助在论文内部找对证据。

Haystack 的 `HierarchicalDocumentSplitter` 和 `AutoMergingRetriever` 官方文档，其实就非常清楚地把这个思路表达出来了：文档应该被切成层级结构，在检索时如果多个叶子块都命中，可以上卷返回父块，从而保留更多上下文。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/hierarchicaldocumentsplitter)) ([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/automergingretriever))

---

# 模块 2：Chunking（Coarse / Fine 双层切块）

## 1. 这个模块到底解决什么问题

模块 1 解决的是“文档进库前的统一化”。
模块 2 解决的是“怎么把标准化后的论文切成**适合检索**的单元”。

如果不认真做 chunking，后面通常会出现三类典型问题：

### 第一类：切得太碎

你能命中局部句子，但上下文不够，模型看不懂。
比如只召回一句“we use retrieval planning…”，却不知道这是方法、实验还是局限。

### 第二类：切得太大

你保住了上下文，但检索噪声太大。
一整个 section 都进 embedding，dense retrieval 很容易被无关信息稀释。

### 第三类：切法和任务不匹配

论文检索里，你有两个层面的任务：

- 先判断“这篇论文是不是相关”
- 再判断“这篇论文里哪一段支持当前 claim / sub-question”

如果 chunk 只有一种粒度，就很难同时兼顾这两个目标。

RAG 相关综述基本都承认，chunking 是 retrieval quality 的关键变量之一。比如 Yepes 等人在论文 *Financial Report Chunking for Effective Retrieval Augmented Generation* 里明确指出，传统 paragraph-level chunking 会忽略文档结构，影响检索效果；近两年的 chunking 研究也普遍在强调“固定切块会破坏语义边界和层级关系”。([arxiv.org](https://arxiv.org/pdf/2402.05131)) ([arxiv.org](https://arxiv.org/html/2506.16035v1)) ([arxiv.org](https://arxiv.org/pdf/2603.25333))

所以模块 2 的目标非常明确：

**把标准化论文切成“适合论文级召回”的 coarse chunks 和“适合证据级召回”的 fine chunks。**

---

## 2. 为什么这里必须做双层切块

你这个系统不是普通 FAQ RAG，而是 research workflow。
所以它的 retrieval 目标有两个层级：

### 层级 A：Paper-level retrieval

这里的目标不是直接回答，而是判断：

- 这篇论文和 query / sub-question 是否相关
- 它是否值得进入候选论文集

这一步更适合：

- 标题
- 摘要
- section 级块
- 合理长度的 coarse chunk

### 层级 B：Evidence-level retrieval

这里的目标是找：

- 支持某个方法描述的段落
- 支持某个结果对比的段落
- 支持 reviewer 检查 citation / claim 的证据块

这一步更适合：

- 细粒度段落
- 句群
- 窗口型 fine chunk

这就是为什么你前面设计里要分 `PaperCandidate` 和 `EvidenceChunk`，它们本来就不该来自同一种 chunk。

LangChain 的 retrieval 文档虽然比较通用，但它也把“loaders → split into chunks → store → retrieve”作为基本流水线，并且 parent-child retrieval 思想本质上就是在承认“不同粒度块服务不同检索目标”。([docs.langchain.com](https://docs.langchain.com/oss/python/langchain/retrieval))

---

## 3. 这个模块的推荐实现思路

我建议你把 chunking 模块拆成三个子层：

### 3.1 Structure-aware Segmentation

先按论文结构切第一刀，而不是直接按 token 切。

优先利用：

- 标题 / 摘要 / 引言 / 方法 / 实验 / 结论
- section heading
- page / paragraph boundary

因为论文是高度结构化文档，结构本身就是很强的先验。
Haystack 的层级切块器也是沿这个方向，把整篇文档拆成树状 block，而不是一视同仁地平铺。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/hierarchicaldocumentsplitter))

### 3.2 Coarse Chunk Builder

在结构边界内构建较大的 chunk，服务于 paper-level retrieval。

推荐来源：

- 标题 + 摘要
- section intro
- 方法概览段
- 实验设置总述
- 结论段

### 3.3 Fine Chunk Builder

在 coarse chunk 内再细切，服务于 evidence retrieval。

推荐粒度：

- paragraph
- sentence group
- sliding window over paragraph

Haystack 还有 `EmbeddingBasedDocumentSplitter`，它本质上就是在尝试做“基于语义相似度的切分点判断”，说明工程上也已经在往“不要纯固定大小切块”这条路走。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/next/embeddingbaseddocumentsplitter))

---

## 4. 推荐的数据对象

模块 2 做完，建议至少产出两类对象。

### `CoarseChunk`

```text
CoarseChunk
- chunk_id
- doc_id
- canonical_id
- section
- page_start
- page_end
- text
- token_count
- order
- parent_chunk_id(optional)
- metadata
```

### `FineChunk`

```text
FineChunk
- chunk_id
- doc_id
- canonical_id
- parent_chunk_id
- section
- page_start
- page_end
- text
- token_count
- order
- metadata
```

这里最关键的是：

- `FineChunk` 必须知道它属于哪个 `CoarseChunk`
- 两者都要保留 `section / page / order`

因为后面：

- reviewer 要看 citation reachability
- extractor 要知道证据属于方法还是结果
- auto-merging / parent retrieval 要知道父子关系

---

## 5. 具体切法怎么定

## 5.1 Coarse Chunk 怎么切

coarse chunk 的设计目标不是“最精确”，而是“适合做论文候选召回”。

我建议优先采用：

### 方案 A：按 section/paragraph group 切

如果文档结构提取比较稳定，这是最优先方案。

例如：

- abstract 单独一块
- introduction 按 2\~4 段合成一块
- method 按子节分块
- experiments 按子节分块
- conclusion 单独一块

这是最贴论文结构的。

### 方案 B：结构感知 + token 上限

如果 section 太长，就在 section 内再做二次切分，但尽量不跨 section 边界。

### 推荐大小

不用死记一个数字，但经验上：

- coarse chunk 通常比 fine chunk 大 2\~4 倍
- 目标是让一个 coarse chunk 能完整表达一个局部主题

这里不要执着“512 token 还是 768 token”，更重要的是：
**它是不是一个完整局部主题块。**

---

## 5.2 Fine Chunk 怎么切

fine chunk 的设计目标是：
**更容易精确命中 supporting evidence。**

我建议两种常用方式：

### 方案 A：按段落切

最稳，最容易落地。
适合论文 PDF 转文本后段落边界还不错的情况。

### 方案 B：句群 + 滑动窗口

比如 2\~5 句为一组，必要时带少量 overlap。

适合：

- 某些关键信息跨句表达
- 单段过长
- 需要更精细 evidence 命中

### overlap 要不要加

fine chunk 可以适当加小 overlap，
但 coarse chunk 不建议重 overlap。

原因很简单：

- coarse chunk 的目的是主题召回，重复太多会污染 paper-level ranking
- fine chunk 的目的是避免证据断裂，适度 overlap 是值得的

---

## 5.3 一个推荐的双层切块流程

```text
Standardized Document
        ↓
Detect structure
(title / abstract / sections / paragraphs)
        ↓
Build Coarse Chunks
(section-aware, theme-preserving)
        ↓
Within each Coarse Chunk
        ↓
Build Fine Chunks
(paragraph / sentence-group / small overlap)
        ↓
Persist chunk tree
(parent-child links + section/page/order)
```

---

## 6. 这个模块和后面模块怎么衔接

这个模块做完之后，后面至少有三层直接受益。

### 对模块 3（Index & Store）

- coarse chunks 进 paper-level vector index / keyword index
- fine chunks 进 evidence-level vector index

### 对模块 4（Paper-level Retrieval）

- 不再直接在所有小碎块上做论文候选召回
- 而是在标题/摘要/coarse chunk 上做 hybrid retrieval

### 对模块 6（Evidence Retrieval）

- 在选中的 papers 内部，用 fine chunk 做二次召回
- 然后构建 `EvidenceChunk[]` 和 `RagResult`

这和你已经写出来的 Phase 2 结构是完全对齐的：先 paper candidates，再 per-paper / per-sub-question evidence chunks，再 build `RagResult`。

---

## 7. 推荐工程结构

```text
src/corpus/ingest/chunkers/
  structure_detector.py
  coarse_chunker.py
  fine_chunker.py
  chunk_linker.py
```

### 各文件职责

`structure_detector.py`

- 识别标题、摘要、section、paragraph、page break

`coarse_chunker.py`

- 生成 coarse chunks
- 保留主题完整性

`fine_chunker.py`

- 在 coarse chunk 内生成 fine chunks
- 保留轻量 overlap

`chunk_linker.py`

- 建 parent-child 关系
- 记录 page / order / section inheritance

这样后面如果你想换 chunking 方法，比如从 paragraph 切换到 embedding-based split，只改对应模块就行。

---

## 8. 模块 2 的流图

### 总体流图

```text
Standardized Document
        ↓
Structure Detector
  ├─ title
  ├─ abstract
  ├─ section headings
  ├─ paragraph boundaries
  └─ page boundaries
        ↓
Coarse Chunk Builder
  ├─ abstract chunk
  ├─ intro chunks
  ├─ method chunks
  ├─ experiment chunks
  └─ conclusion chunk
        ↓
Fine Chunk Builder
  ├─ paragraph chunks
  ├─ sentence-group chunks
  └─ local overlap
        ↓
Chunk Linker
  ├─ parent-child relations
  ├─ section/page metadata
  └─ order metadata
        ↓
CoarseChunk[] + FineChunk[]
```

### 和 retrieval 的衔接流图

```text
CoarseChunk[]
   ↓
paper-level hybrid retrieval
   ↓
Top-K PaperCandidate
   ↓
FineChunk[] within selected papers
   ↓
evidence retrieval
   ↓
EvidenceChunk[]
```

---

## 9. 设计参考

### 论文参考

1. **Yepes et al.,**  ***Financial Report Chunking for Effective Retrieval Augmented Generation***
   这篇很适合拿来支撑“为什么不能只做简单 paragraph-level chunking”。它明确指出，传统切法忽视文档结构，对复杂长文档检索不理想。([arxiv.org](https://arxiv.org/pdf/2402.05131))
2. **Vision-Guided Chunking Is All You Need: Enhancing RAG...** 
   这篇总结得很直白：固定大小切块容易打断语义单元，sentence-based chunking 虽然自然一点，但仍然忽略文档层级结构。这个观点非常适合给你现在的“论文 RAG 为什么要双层切块”做理论支撑。([arxiv.org](https://arxiv.org/html/2506.16035v1))
3. **Optimizing Chunking-Method Selection for RAG**
   这篇近年的工作进一步强调 chunking 的“context-preservation dilemma”，也就是切得太碎和切得太大都不对。它适合支撑你为什么要 coarse / fine 双层，而不是单粒度。([arxiv.org](https://arxiv.org/pdf/2603.25333))

### 博客 / 官方文档参考

1. **Haystack – HierarchicalDocumentSplitter**
   官方直接给出层级切块的工程实现思路，非常贴你现在的双层 chunk 设计。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/hierarchicaldocumentsplitter))
2. **Haystack – AutoMergingRetriever**
   它说明了为什么多个 leaf chunk 命中时，返回 parent chunk 往往更有价值，这和你 coarse/fine 双层设计高度一致。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/automergingretriever))
3. **Haystack – EmbeddingBasedDocumentSplitter**
   适合做后续增强参考：如果你后面不满足于 rule-based chunking，可以往语义断点切块走。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/next/embeddingbaseddocumentsplitter))

---

## 11. 模块 2 的交付物

这个模块做完，最少要能交付：

- `CoarseChunk[]`
- `FineChunk[]`
- parent-child chunk graph
- section/page/order metadata
- 一个统一 chunking pipeline
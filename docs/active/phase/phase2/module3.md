**模块 3：Index & Store**。
这一步就是你刚才追问的那部分：**向量数据库 / 向量索引到底放在哪里、怎么和关键词索引、元数据索引一起设计**。

前面模块 1 做完以后，你已经有了标准化的 `Document`；模块 2 做完以后，你已经有了 `CoarseChunk[]` 和 `FineChunk[]`。模块 3 的任务，就是把这些对象真正写入可检索的存储层，并组织成后面 **paper-level hybrid retrieval** 和 **evidence-level retrieval** 能直接调用的索引结构。你前面的 Phase 2 设计里也已经明确把这一层定义成 `document store / chunk store / vector index / keyword index / metadata index`，而不是只说“上一个向量库”。

---

# 模块 3：Index & Store

## 1. 这个模块解决什么问题

模块 2 只是把论文切好了，但“切好”不等于“能高质量检索”。

真正到了检索阶段，你至少会同时遇到 3 类查询信号：

第一类是 **语义相似**。
比如用户问“用于科研综述的多智能体系统”，但论文标题写的是 “multi-agent framework for literature review automation”。这类需要 dense retrieval。RAG 综述也普遍把 dense retrieval 视为现代 RAG 的核心组成之一。([arxiv.org](https://arxiv.org/abs/2312.10997?utm_source=chatgpt.com)) ([arxiv.org](https://arxiv.org/abs/2405.06211?utm_source=chatgpt.com))

第二类是 **关键词精确匹配**。
比如模型名、数据集名、作者名、venue、年份、arXiv id，这类 BM25/关键词检索非常强。Haystack 官方 retriever 列表里也一直把 BM25、Embedding、Hybrid 作为并行存在的检索器，而不是认为 dense 可以完全替代 lexical。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/retrievers))

第三类是 **结构化过滤**。
比如只看 2023–2026 年，只查 uploaded PDFs，只看某个 workspace 的本地论文，或者只查 methods section。这个时候单纯向量相似度不够，需要 metadata filtering。Qdrant 的官方文档就把 filtering 作为向量检索里的核心能力之一。([qdrant.tech](https://qdrant.tech/documentation/search/filtering/))

所以模块 3 的目标不是“把 embedding 丢进向量数据库”，而是：

**构建一套同时支持 dense、lexical、metadata-aware retrieval 的索引与存储层。**

---

## 2. 这个模块的总体职责

我建议把这个模块理解成 5 个并列子层：

### 2.1 Document Store

存储标准化后的论文文档对象。

### 2.2 Chunk Store

存储 `CoarseChunk` 和 `FineChunk`，包括 parent-child 关系。

### 2.3 Vector Index

为 coarse/fine chunk 提供 embedding 检索能力。

### 2.4 Keyword Index

为 title/abstract/chunk 提供 BM25 或全文检索能力。

### 2.5 Metadata Index

支持 source / year / venue / section / canonical\_id 等过滤和聚合。

Haystack 官方对 `Document Store` 的定义其实和你这里非常一致：它把 document store 视为“存储文档并为 retriever 提供数据的数据库接口”，而不是 pipeline 节点本身；同时它也明确推荐不同 store 搭配不同 retriever。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/document-store)) ([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/retrievers))

---

## 3. 为什么这里不要只说“向量数据库”

因为在架构层，**你真正需要的是向量索引能力，而不是先绑定某个产品名**。

也就是说：

- 逻辑设计层写 `vector index`
- 部署实现层再落成 Qdrant / Milvus / pgvector / Elasticsearch dense vector / FAISS 等具体产品

这样做的好处是后续可替换，而且不会把架构设计写死成某个中间件。

你前面已经把这层抽象成：

```text
document store
chunk store
vector index
keyword index
metadata index
```

这个抽象是对的，因为你现在真正设计的是 **retrieval capability layout**，不是先做采购清单。

---

## 4. 推荐的存储结构

## 4.1 Document Store

Document Store 主要存的是论文级对象，而不是检索主入口。

建议存：

```text
Document
- doc_id
- canonical_id
- source_ref
- title
- authors
- year
- venue
- doi
- arxiv_id
- abstract
- raw_text_ref
- ingest_status
```

### 用途

- 回显论文元数据
- 构造 `PaperCandidate`
- 做 canonical paper merge
- 给 reviewer/citation reachability 用

它本身不一定承担高频向量检索，但一定是**论文身份和来源真相源**。

---

## 4.2 Chunk Store

Chunk Store 是实际检索更常用的数据层。

建议至少分两张逻辑表：

### `coarse_chunks`

服务 paper-level retrieval

### `fine_chunks`

服务 evidence retrieval

建议字段：

```text
Chunk
- chunk_id
- doc_id
- canonical_id
- chunk_kind         # coarse / fine
- parent_chunk_id
- text
- token_count
- section
- page_start
- page_end
- order
- metadata
```

### 为什么 document 和 chunk 分开

因为：

- document 负责“论文是什么”
- chunk 负责“检索命中什么”

这两个层级不要混。

---

## 5. Vector Index 怎么设计

这部分就是你关心的“向量数据库到底在哪”。

## 5.1 写入对象

建议至少有两套向量索引：

### `coarse_vector_index`

- 输入：`CoarseChunk`
- 用途：paper-level retrieval

### `fine_vector_index`

- 输入：`FineChunk`
- 用途：evidence retrieval

这样做的原因很直接：
论文级召回和证据级召回，不该共用同一种粒度的 embedding 单元。

---

## 5.2 为什么要分 coarse 和 fine 两套向量索引

如果你只有 fine chunk 向量库，paper-level retrieval 会被很多碎片噪声污染。
如果你只有 coarse chunk 向量库，evidence retrieval 又会太粗，不利于 reviewer 和 citation grounding。

所以最自然的设计就是：

```text
CoarseChunk[] → coarse_vector_index
FineChunk[]   → fine_vector_index
```

然后后面：

- 模块 4 用 coarse 做 paper recall
- 模块 6 用 fine 做 evidence recall

这和你前面定下的 hierarchical retrieval 路线是一致的。

---

## 5.3 选型怎么想

### 方案 A：MVP / 本地开发

- FAISS 做 dense index
- SQLite / Postgres 存 document + metadata
- BM25 用 Whoosh / Elasticsearch / 本地全文检索补

适合：

- 早期实验
- 单机 workspace
- 不追求复杂过滤

### 方案 B：工程化推荐

- Qdrant 或 Milvus 做向量索引
- Postgres/MySQL 做 document metadata truth store
- 关键词检索用 Elasticsearch / OpenSearch，或统一落在支持 hybrid 的后端

Qdrant 官方非常强调 filtering，适合做 metadata-aware vector retrieval；Milvus 则更偏标准向量库路线。([qdrant.tech](https://qdrant.tech/documentation/search/filtering/)) ([milvus.io](https://milvus.io/docs/v2.3.x/hybridsearch.md))

### 方案 C：统一后端

- Elasticsearch / OpenSearch 同时做 BM25 + dense vector + hybrid search

Elastic 官方对 hybrid search 的介绍非常适合作为这个方案的参考，因为它天然支持 lexical 与 semantic 的结合。([elastic.co](https://www.elastic.co/search-labs/blog/hybrid-search-elasticsearch))

### 我对你这个业务的建议

如果你现在目标是 **research workflow + workspace + 多来源论文库 + 后续 reviewer / eval**，我更推荐两条路线：

#### 路线 1：Qdrant + Postgres

更清楚、更模块化。

- Qdrant：dense retrieval + filtering
- Postgres：document/chunk truth store + metadata
- 关键词检索：后续可补 pgvector keyword 或 ES

#### 路线 2：Elasticsearch/OpenSearch 一体化

如果你更重视 hybrid search 和统一运维，可以考虑这一类。

---

## 6. Keyword Index 怎么设计

不要省这一层。
论文场景里，关键词检索极其重要。

## 6.1 为什么一定要有 keyword index

因为有些信号 dense retrieval 不擅长：

- “GraphRAG”
- “SWE-bench”
- “LlamaIndex”
- 特定作者名
- 特定年份
- arXiv id
- venue 缩写

这些通常 lexical match 更稳。

Haystack 官方 retriever 列表本身就同时保留了：

- BM25 retrievers
- embedding retrievers
- hybrid retrievers
  说明工程上它们是互补关系，不是替代关系。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/retrievers))

---

## 6.2 建议索引哪些字段

对于 paper-level retrieval，建议至少建：

- title
- abstract
- authors
- venue
- keywords
- coarse chunk text

对于 evidence retrieval，如果你后面要支持 keyword fallback，也可以给 fine chunk 建轻量全文索引，但优先级低于 coarse。

---

## 6.3 与 vector index 的关系

不是二选一，而是并行：

```text
query
 ├─ keyword retriever
 └─ vector retriever
      ↓
candidate merge
      ↓
dedup
      ↓
rerank
```

这其实就是你前面一直在说的 **hybrid retrieval** 主线。

---

## 7. Metadata Index 怎么设计

这一层非常关键，因为你后面的 API 已经明确要求支持：

- years filter
- sources filter
- workspace scope
- top\_k papers
- top\_k chunks。

## 7.1 推荐 metadata 字段

建议至少支持这些 filterable fields：

```text
- workspace_id
- source_type
- canonical_id
- doc_id
- year
- venue
- authors
- section
- chunk_kind
- ingest_status
- version
```

## 7.2 为什么 metadata filter 重要

因为 research workflow 里，用户很可能会问：

- 只看 2024 年后的论文
- 只看 uploaded PDF
- 只看本地论文库
- 只在 methods section 找证据
- 只在某个 workspace 内检索

这些需求不可能只靠 embedding 距离来做。

Qdrant 官方文档的 filtering 部分，其实就是在回答这个问题：向量检索必须能和条件过滤结合，否则真实业务很难用。([qdrant.tech](https://qdrant.tech/documentation/search/filtering/))

---

## 8. 推荐工程结构

```text
src/corpus/store/
  document_store.py
  chunk_store.py
  vector_index.py
  keyword_index.py
  metadata_index.py
  repository.py
```

### 各层职责

`document_store.py`

- 管论文级元数据
- `get_document / upsert_document / list_by_canonical_id`

`chunk_store.py`

- 管 chunk truth store
- parent-child / page / section 信息

`vector_index.py`

- `index_coarse_chunks`
- `index_fine_chunks`
- `search_coarse`
- `search_fine`

`keyword_index.py`

- BM25 / full-text search
- title/abstract/coarse chunk lexical recall

`metadata_index.py`

- filter compiler
- workspace / source / year / section 过滤

`repository.py`

- 把 store/index 统一成对上层可调用的 API

这样模块 4/5 的 retriever 就不用直接知道底层到底是 Qdrant 还是 Elastic。

---

## 9. 模块 3 的流图

### 总体流图

```text
Document + CoarseChunk[] + FineChunk[]
              ↓
       Store Writer Layer
   ├─ Document Store
   ├─ Chunk Store
   ├─ Vector Index
   ├─ Keyword Index
   └─ Metadata Index
              ↓
   ready for hybrid retrieval
```

### 更细一点的写入流图

```text
Standardized Document
        ↓
write Document Store
        ↓
CoarseChunk[] ----------------→ coarse_vector_index
        └--------------------→ coarse_keyword_index
        ↓
FineChunk[] ------------------→ fine_vector_index
        └--------------------→ fine_metadata_records
        ↓
metadata fields → metadata index / filter layer
```

### 和后面模块的衔接流图

```text
Paper Query
   ├─ keyword search on title/abstract/coarse
   ├─ dense search on coarse_vector_index
   └─ metadata filters
        ↓
candidate papers
        ↓
dedup + paper rerank
        ↓
selected papers
        ↓
dense search on fine_vector_index
        ↓
evidence chunks
```

---

## 10. 设计参考

### 论文参考

1. **Gao et al.,**  ***Retrieval-Augmented Generation for Large Language Models: A Survey***
   这篇适合支撑“dense retrieval 只是 RAG 的一个组成部分，系统设计是 modular 的”这个总论点。([arxiv.org](https://arxiv.org/abs/2312.10997?utm_source=chatgpt.com))
2. **Fan et al.,**  ***A Survey on RAG Meeting LLMs***
   这篇更适合支撑你现在这种模块化、可组合的研究型 RAG 设计。([arxiv.org](https://arxiv.org/abs/2405.06211?utm_source=chatgpt.com))

### 博客 / 官方文档参考

1. **Haystack – Document Store**
   适合引用“Document Store 是 retriever 访问数据的数据库接口，而不是 pipeline component”。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/document-store))
2. **Haystack – Retrievers**
   适合引用“BM25、Embedding、Hybrid retrievers 是并存的工程选项”。([docs.haystack.deepset.ai](https://docs.haystack.deepset.ai/docs/retrievers))
3. **Elastic – Hybrid Search**
   适合引用为什么要把 lexical 和 semantic 检索结合。([elastic.co](https://www.elastic.co/search-labs/blog/hybrid-search-elasticsearch))
4. **Qdrant – Filtering**
   适合引用为什么 metadata filtering 是生产检索系统的基本能力。([qdrant.tech](https://qdrant.tech/documentation/search/filtering/))
5. **Pinecone – Rerankers and Two-Stage Retrieval**
   虽然更贴模块 5，但它对“索引层只负责高召回，精排放后面”的解释很适合现在先埋个伏笔。([pinecone.io](https://www.pinecone.io/learn/series/rag/rerankers/))

---

## 11. 这个模块做完后的交付物

模块 3 做完，应该至少交付这些东西：

- `DocumentStore`
- `ChunkStore`
- `coarse_vector_index`
- `fine_vector_index`
- `keyword_index`
- `metadata filter layer`
- 统一的 `repository/service` 访问接口

以及一组可被上层调用的能力：

- `search_coarse_dense()`
- `search_coarse_keyword()`
- `search_fine_dense()`
- `apply_filters()`
- `get_document_by_id()`
- `get_chunks_by_canonical_id()`


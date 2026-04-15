# PaperReader Agent — RAG 检索架构详解

---

## 1. 三层检索架构

### 1.1 整体检索流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    Search Node — 三源并行检索                      │
│                                                                  │
│  ResearchBrief.topic + SearchPlan.query_groups                    │
│         │                                                         │
│         ▼                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                      │
│  │ SearXNG  │  │ arXiv API│  │ DeepXiv   │   ← 并行（max_workers=3）
│  │ (广度)   │  │ (精度)   │  │ (趋势)   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                      │
│       │              │              │                              │
│       └──────────────┴──────────────┘                              │
│                      │                                             │
│                      ▼                                             │
│              Deduper（按 arxiv_id 去重）                           │
│              优先级：arXiv > DeepXiv > SearXNG                      │
│                      │                                             │
│                      ▼                                             │
│           enrich_search_results_with_arxiv                          │
│           （批量补充元数据：作者、年份、venue）                       │
│                      │                                             │
│                      ▼                                             │
│           _ingest_paper_candidates                                 │
│           （前 50 篇写入 PostgreSQL ChunkStore）                    │
│                      │                                             │
│                      ▼                                             │
│           RagResult(paper_candidates=[...])                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 三源检索详解

### 2.1 SearXNG — 多引擎聚合搜索

**文件**：`src/tools/search_tools.py`

```python
def _searxng_search(query: str, engines: list[str] | None = None) -> list[dict]:
    """
    SearXNG 搜索：

    优势：
    - 无需 API key，多引擎聚合（Google Scholar、Bing Academic 等）
    - 支持并发多查询（ThreadPoolExecutor max_workers=8）
    - 适合广度召回：发现不在关键词中的相关论文

    劣势：
    - 可能返回非学术来源（需后处理过滤）
    - 依赖 SearXNG 服务可用性
    """
    base_url = settings.searxng_base_url
    params = {
        "q": query,
        "engines": engines or ["arxiv", "google scholar"],
        "format": "json",
    }
    response = httpx.get(f"{base_url}/search", params=params, timeout=15.0)
    results = response.json().get("results", [])
    return [
        {
            "url": r["url"],
            "title": r["title"],
            "content": r["content"],
            "source": "searxng",
        }
        for r in results
    ]
```

### 2.2 arXiv API — 权威来源精确检索

**文件**：`src/tools/arxiv_api.py`

```python
def search_arxiv_direct(query: str, max_results: int = 10) -> list[dict]:
    """
    arXiv API 直连搜索：

    优势：
    - 权威来源，元数据完整（arxiv_id, authors, categories, abstract）
    - 结果可直接 enrich
    - 支持多种查询语法（ti:、au:、abs:、all:）

    实现方式：
    - feedparser 解析 Atom feed
    - 解析结果映射为 dict（保留 key 字段）
    """
    import feedparser

    url = f"http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
    }
    feed = feedparser.parse(f"{url}?{urlencode(params)}")

    results = []
    for entry in feed.entries:
        arxiv_id = entry.id.split("/")[-1]
        results.append({
            "arxiv_id": arxiv_id,
            "title": entry.title,
            "authors": [a.name for a in entry.authors],
            "abstract": entry.summary,
            "published": entry.published,
            "categories": [t.term for t in entry.tags],
        })
    return results
```

### 2.3 DeepXiv — 学术专注的补充搜索

**文件**：`src/tools/deepxiv_client.py`

```python
def search_deepxiv(query: str, max_results: int = 5) -> list[dict]:
    """
    DeepXiv 搜索：

    特点：
    - 专门针对学术论文的语义搜索
    - 支持热度排序（trending papers）
    - 可补充 SearXNG 和 arXiv 未召回的论文
    """
    response = httpx.post(
        f"{settings.deepxiv_base_url}/search",
        json={"query": query, "top_k": max_results},
        timeout=20.0,
    )
    return response.json().get("results", [])
```

---

## 3. 去重与优先级策略

**文件**：`src/corpus/search/deduper.py`

```python
def dedupe_by_arxiv_id(candidates: list[dict]) -> list[dict]:
    """
    按 arxiv_id 精确去重，保留优先级最高的结果。

    优先级：arXiv API > DeepXiv > SearXNG

    理由：
    - arXiv API 有完整的元数据（可直接 enrich）
    - DeepXiv 有语义排序（质量较高）
    - SearXNG 是广度召回（元数据不完整）
    """
    seen = set()
    result = []

    for item in candidates:
        arxiv_id = item.get("arxiv_id") or _extract_arxiv_id(item.get("url", ""))
        if not arxiv_id:
            continue

        if arxiv_id not in seen:
            seen.add(arxiv_id)
            # 记录来源优先级（数字越小优先级越高）
            item["_priority"] = {"arxiv": 0, "deepxiv": 1, "searxng": 2}.get(item.get("source", ""), 3)
            result.append(item)

    # 按优先级排序（同一论文保留最高优先级来源）
    result.sort(key=lambda x: x["_priority"])
    return result


def _extract_arxiv_id(url: str) -> str | None:
    """从 URL 中提取 arXiv ID"""
    import re
    match = re.search(r"arxiv\.org/abs/(\d+\.\d+)", url)
    return match.group(1) if match else None
```

---

## 4. 向量检索与 Reranker

### 4.1 向量检索现状

**文件**：`src/corpus/store/vector_index.py`

当前系统存在**两套向量检索**：

| 实现 | 状态 | 位置 |
|------|------|------|
| **FAISS** | ✅ 已实现 | `src/corpus/store/vector_index.py` |
| **PostgreSQL + pgvector** | ⚠️ 未配置 | 文档有，但未启用 |

```python
class FAISSVectorIndex:
    """本地 FAISS 向量索引（用于 chunk 检索）"""

    def __init__(self, dimension: int = 768):
        self.index = faiss.IndexFlatIP(dimension)  # 内积相似度
        self.doc_ids: list[str] = []

    def add(self, doc_id: str, embedding: list[float]) -> None:
        # L2 归一化后用内积等价余弦相似度
        norm = np.linalg.norm(embedding)
        vec = np.array(embedding) / norm
        self.index.add(vec.reshape(1, -1))
        self.doc_ids.append(doc_id)

    def search(self, query_embedding: list[float], k: int = 10) -> list[tuple[str, float]]:
        norm = np.linalg.norm(query_embedding)
        vec = np.array(query_embedding) / norm
        scores, indices = self.index.search(vec.reshape(1, -1), k)
        return [(self.doc_ids[i], float(scores[0][j])) for j, i in enumerate(indices[0])]
```

**注意**：当前 `evidence_chunks` 在 search_node 返回的 `RagResult` 中始终为空（`[]`），说明向量检索链路未在 Research Graph 中真正启用。

### 4.2 CrossEncoder Reranker

**文件**：`src/corpus/search/reranker.py`

```python
class CrossEncoderReranker:
    """
    本地 Cross-Encoder Reranker — 对候选论文做语义重排。

    模型选择：cross-encoder/ms-marco-MiniLM-L-6-v2
    - 专为 MS MARCO passage ranking 训练
    - 6 层 MiniLM，速度快（~10ms/query）
    - 在学术论文检索场景表现优异

    对比 Bi-Encoder：
    - Bi-Encoder：query 和 doc 分别编码，cosine 相似度排序
    - Cross-Encoder：query+doc 拼接后联合编码，打分更准确但无法预计算
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

    def rerank(
        self,
        query: str,
        candidates: list[DedupedCandidate],
        top_k: int = 10,
    ) -> list[RerankResult]:
        """
        对候选论文 rerank：

        Args:
            query: 研究主题 / 子问题
            candidates: 去重后的候选论文列表
            top_k: 返回 top_k 条

        Returns:
            按 Cross-Encoder 打分降序排列的结果
        """
        pairs = [(query, c.title + " " + c.abstract) for c in candidates]
        inputs = self.tokenizer(pairs, padding=True, truncation=True, return_tensors="pt")

        with torch.no_grad():
            scores = self.model(**inputs).logits.squeeze(-1).numpy()

        # 按打分降序排列
        sorted_indices = np.argsort(scores)[::-1]
        return [
            RerankResult(
                doc_id=candidates[i].doc_id,
                canonical_id=candidates[i].canonical_id,
                rerank_score=float(scores[i]),
                rerank_index=int(i),
            )
            for i in sorted_indices[:top_k]
        ]
```

**RRF 融合**（`rerank_with_fusion`）：

```python
def rerank_with_fusion(
    query: str,
    keyword_candidates: list[DedupedCandidate],
    vector_candidates: list[DedupedCandidate] | None = None,
    rrf_k: int = 60,
    cross_encoder_weight: float = 0.6,
) -> list[RerankResult]:
    """
    RRF（Reciprocal Rank Fusion）+ Cross-Encoder 加权融合：

    score = (1 - cross_encoder_weight) * RRF(keyword_rank)
          + cross_encoder_weight * CE_score_normalized

    默认配置：40% RRF + 60% Cross-Encoder

    理由：
    - RRF 对不同检索源的结果做排名融合（适合混合检索）
    - Cross-Encoder 打分提供语义精细排序
    """
    # ... 实现见 reranker.py
```

**⚠️ 当前状态**：`search_node` 最终排序**未调用 reranker**，候选论文按 dedup 顺序直接返回。这是待优化的工程点。

---

## 5. Chunk 存储与 Evidence 检索

### 5.1 Chunk 模型

**文件**：`src/corpus/models.py`

```python
class CoarseChunk(BaseModel):
    """粗粒度 chunk：论文级别的摘要块"""
    doc_id: str
    chunk_id: str
    text: str                    # 摘要全文
    chunk_type: Literal["abstract", "introduction", "method", "result"]

class FineChunk(BaseModel):
    """细粒度 chunk：段落级别的句子块（用于 evidence retrieval）"""
    doc_id: str
    chunk_id: str
    text: str                    # 句子块（350 chars / chunk）
    start_char: int
    end_char: int
    section: str
    overlap_chars: int = 60     # 前后重叠 60 chars
```

### 5.2 ChunkStore — PostgreSQL 持久化

**文件**：`src/corpus/store/chunk_store.py`

```python
class ChunkStore:
    """PostgreSQL ChunkStore：存储 coarse + fine chunks"""

    async def store_coarse_chunks(self, chunks: list[CoarseChunk]) -> None:
        """批量存储粗粒度 chunks"""
        async with get_async_session() as session:
            session.add_all([CoarseChunkDB(**c.model_dump()) for c in chunks])
            await session.commit()

    async def store_fine_chunks(self, chunks: list[FineChunk]) -> None:
        """批量存储细粒度 chunks"""
        async with get_async_session() as session:
            session.add_all([FineChunkDB(**c.model_dump()) for c in chunks])
            await session.commit()

    async def search_evidence(
        self,
        doc_id: str,
        claim: str,
        top_k: int = 5,
    ) -> list[EvidenceChunk]:
        """
        基于 claim 检索 evidence chunks：

        当前实现：BM25 关键词检索
        理想实现：向量检索（embedding similarity）
        """
        chunks = await self.get_chunks_by_doc(doc_id)
        # BM25 scoring
        scores = {c.chunk_id: self._bm25_score(c.text, claim) for c in chunks}
        top_chunks = sorted(chunks, key=lambda c: scores[c.chunk_id], reverse=True)[:top_k]
        return [EvidenceChunk(**c.model_dump(), relevance_score=scores[c.chunk_id]) for c in top_chunks]
```

---

## 6. 三层检索架构总结

| 层级 | 技术 | 作用 | 当前状态 |
|------|------|------|---------|
| **L0: 关键词召回** | SearXNG + arXiv API | 广度发现候选论文 | ✅ 生产可用 |
| **L1: 语义重排** | CrossEncoder Reranker | 精细化排序 | ⚠️ 实现了但未接入 |
| **L2: 向量检索** | FAISS / pgvector | 精准 evidence retrieval | ⚠️ Chunk 存储了但未用于检索 |
| **L3: Evidence Grounding** | BM25 / Citation Resolution | claim-level 引用验证 | ✅ 生产可用 |

---

## 7. 技术优势总结

| 优势 | 实现方式 |
|------|---------|
| **多源互补** | SearXNG（广度）+ arXiv（精度）+ DeepXiv（趋势） |
| **优先级去重** | arXiv > DeepXiv > SearXNG，保留最佳元数据 |
| **批量 enrich** | 一次 DB 查询批量补充元数据，减少网络开销 |
| **两阶段排序** | BM25 初排 + CrossEncoder 精排（RRF 融合） |
| **PGVector 架构设计** | PostgreSQL + pgvector 统一持久化（虽然未启用） |

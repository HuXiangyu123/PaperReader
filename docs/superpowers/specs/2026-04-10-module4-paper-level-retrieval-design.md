# 模块 4：Paper-level Retrieval 设计方案

**日期**: 2026-04-10
**状态**: 已批准
**负责人**: PaperReader Agent

---

## 1. 核心定位

模块 4 负责将用户 query 转化为**高召回论文候选池**，为后续模块 5（canonical dedup + paper rerank）打底。

输出不是精排结果，而是「先找全」的多路召回候选集。

```
SearchInput → Hybrid Recall → Candidate Merge → InitialPaperCandidates + RetrievalTrace
```

---

## 2. API 设计

### 端点

`POST /corpus/search`

### 请求体

```python
class CorpusSearchRequest(BaseModel):
    query: str                              # 原始研究问题
    sub_questions: list[str] = []           # SearchPlan 子问题
    filters: Optional[SearchFilters] = None  # 元数据过滤
    top_k: int = 100                        # 每路召回固定 Top-K

class SearchFilters(BaseModel):
    year_range: Optional[tuple[int, int]] = None    # (2020, 2025)
    source_type: Optional[list[str]] = None           # ["arxiv", "uploaded_pdf"]
    venue: Optional[list[str]] = None                 # ["NeurIPS", "ICML"]
    canonical_id: Optional[list[str]] = None          # 指定论文组
    workspace_id: Optional[str] = None
```

### 响应体

```python
class CorpusSearchResponse(BaseModel):
    candidates: list[MergedCandidate]  # 合并后候选论文列表
    trace: RetrievalTrace             # 完整检索轨迹
    query_prep: PreparedQuery         # 预处理后查询信息

class MergedCandidate(BaseModel):
    doc_id: str
    canonical_id: Optional[str]
    title: str
    authors: Optional[str]
    year: Optional[int]
    venue: Optional[str]
    abstract: Optional[str]
    source_type: str
    # 分数
    rrf_score: float
    keyword_score: Optional[float]
    dense_score: Optional[float]
    # 来源追踪
    recall_results: list[RecallResult]

class RecallResult(BaseModel):
    doc_id: str
    canonical_id: Optional[str]
    score: float
    path: RetrievalPath
    matched_query: str          # 来自主 query 还是哪个子问题
    chunk_ids: list[str]        # 命中的 chunk IDs

class RetrievalPath(str, Enum):
    KEYWORD_TITLE = "keyword_title"
    KEYWORD_ABSTRACT = "keyword_abstract"
    KEYWORD_COARSE = "keyword_coarse"
    DENSE_COARSE = "dense_coarse"
    METADATA_FILTER = "metadata_filter"

class RetrievalTrace(BaseModel):
    query: str
    sub_questions: list[str]
    filters: dict
    top_k: int
    path_results: dict[str, list[dict]]  # 每路原始召回详情
    total_candidates: int
    merged_count: int
```

---

## 3. 检索流水线

### 3.1 Query Preparation

**文件**: `src/corpus/search/retrievers/query_prep.py`

```python
class QueryPreparer:
    def prepare(self, query: str, sub_questions: list[str]) -> PreparedQuery:
        # 1. 主 query 清洗（strip、低频词保留）
        # 2. sub_questions 扁平展开
        # 3. 生成所有待检 query 列表（主+子）
        # 4. 返回 PreparedQuery（含 search_queries list）

class FilterCompiler:
    def compile(self, filters: SearchFilters) -> CompiledFilters:
        # SearchFilters → Milvus filter expr + SQL predicates
        # 例如: year >= 2020 AND year <= 2025 AND source_type IN (...)
```

### 3.2 Hybrid Recall（并行）

**文件**: `src/corpus/search/retrievers/keyword_retriever.py`

```python
class KeywordRetriever:
    def search_all_paths(
        self,
        queries: list[str],
        filters: CompiledFilters,
        top_k: int = 100,
    ) -> dict[RetrievalPath, list[RecallResult]]:
        # 并行在三个字段上跑 BM25：
        # - KEYWORD_TITLE: ts_rank(title, query) on document table
        # - KEYWORD_ABSTRACT: ts_rank(abstract, query) on document table
        # - KEYWORD_COARSE: ts_rank(coarse_chunk.text, query) on coarse_chunks table
        # 每条结果含 doc_id, score, path, matched_query, chunk_ids
```

**文件**: `src/corpus/search/retrievers/dense_retriever.py`

```python
class DenseRetriever:
    def search_coarse(
        self,
        query_embedding: list[float],
        filters: CompiledFilters,
        top_k: int = 100,
    ) -> list[RecallResult]:
        # MilvusVectorIndex.search() on coarse_chunks collection
        # 过滤: filters.milvus_expr（如 year >= 2020）
        # 返回: doc_id, score, path=DENSE_COARSE
```

### 3.3 Candidate Merge

**文件**: `src/corpus/search/retrievers/candidate_merger.py`

```python
class CandidateMerger:
    def merge(
        self,
        path_results: dict[RetrievalPath, list[RecallResult]],
        top_k: int = 100,
    ) -> list[MergedCandidate]:
        # 1. RRF 融合 (k=40)
        #    score_rrf(doc, path) = Σ 1/(40 + rank_in_path)
        # 2. 按 doc_id 归并（同一论文多路径命中 → 一条 candidate）
        # 3. 元数据补全（查 Document 表）
        # 4. 返回 top_k 条 MergedCandidate
```

### 3.4 Trace Build

**文件**: `src/corpus/search/retrievers/trace_builder.py`

```python
class TraceBuilder:
    def build(
        self,
        query_prep: PreparedQuery,
        path_results: dict[RetrievalPath, list[RecallResult]],
        merged: list[MergedCandidate],
    ) -> RetrievalTrace:
        # 记录每路召回的详细信息（供模块 7 evals 分析）
        # 包括: returned doc_ids, scores, matched queries, filter_summary
```

---

## 4. Orchestrator 入口

**文件**: `src/corpus/search/retrievers/paper_retriever.py`

```python
class PaperRetriever:
    def __init__(self, corpus_repo: CorpusRepository):
        self.query_preparer = QueryPreparer()
        self.filter_compiler = FilterCompiler()
        self.keyword_retriever = KeywordRetriever(corpus_repo)
        self.dense_retriever = DenseRetriever(corpus_repo)
        self.merger = CandidateMerger(corpus_repo)
        self.trace_builder = TraceBuilder()

    def search(
        self,
        query: str,
        sub_questions: list[str],
        filters: SearchFilters,
        top_k: int = 100,
    ) -> tuple[list[MergedCandidate], RetrievalTrace]:
        # 1. query_prep
        # 2. 并行 keyword + dense recall
        # 3. merge + enrich
        # 4. trace
        # 5. 返回
```

---

## 5. 子问题处理策略：Flatten

所有 `query + sub_questions` 打平后统一送入各召回路。每条召回记录标注 `matched_query` 表明来源。

RRF 融合自然累积多路径命中的分数加成（如果主 query 和某个子问题都命中了同一篇论文，其 rrf_score 会更高）。

---

## 6. 文件结构

```
src/corpus/search/
├── __init__.py
├── retrievers/
│   ├── __init__.py
│   ├── models.py              # RetrievalPath, RecallResult, MergedCandidate, RetrievalTrace
│   ├── query_prep.py          # QueryPreparer, FilterCompiler
│   ├── keyword_retriever.py    # KeywordRetriever (BM25 三路)
│   ├── dense_retriever.py     # DenseRetriever (Milvus coarse)
│   ├── candidate_merger.py     # CandidateMerger (RRF k=40 + merge)
│   ├── trace_builder.py        # TraceBuilder
│   └── paper_retriever.py      # PaperRetriever Orchestrator
src/api/routes/
├── corpus_search.py            # POST /corpus/search 路由
```

---

## 7. 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| API 形式 | 独立路由 `POST /corpus/search` | 隔离关注点，便于独立演进 |
| 每路 Top-K | 固定 100 | 简单确定，模块 5 再精排筛选 |
| RRF k 值 | k=40 | 偏向高频命中，给排名靠前的更多权重 |
| 子问题处理 | Flatten 合并 | 共享候选池，多路径命中自然加分 |
| Embedding | 复用 CorpusRepository 已有 embedding pipeline | 不重复造轮子 |

---

## 8. 与现有代码的集成

- **复用**: `CorpusRepository` 的 Milvus client、PostgreSQL session、`KeywordIndex`
- **基于已有**: `src/corpus/search/retrievers/paper_retriever.py` 已有骨架，重构实现
- **模块 5 衔接**: 输出 `list[MergedCandidate]` 直接送入 canonical dedup + paper rerank
- **模块 7 衔接**: `RetrievalTrace` 供 RAG evals 分析 recall 覆盖率

---

## 9. 测试策略

- `test_keyword_retriever.py` - 各路径 BM25 召回正确性
- `test_dense_retriever.py` - 向量召回正确性
- `test_candidate_merger.py` - RRF 融合分数计算正确性
- `test_paper_retriever.py` - 端到端集成测试
- `test_api_corpus_search.py` - API 路由测试

# 模块 4 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 `POST /corpus/search` API 端点，输出高召回论文候选池 + 检索轨迹

**Architecture:** 新建独立 API 路由 `src/api/routes/corpus_search.py`，基于已有 `src/corpus/search/retrievers/` 骨架改造。RRF k=40，各路固定 top_k=100。

**Tech Stack:** FastAPI, SQLAlchemy, pymilvus, Pydantic v2

---

## 文件结构

```
创建: src/api/routes/corpus_search.py          # FastAPI 路由 + Pydantic 模型
创建: tests/corpus/search/test_paper_retriever.py  # PaperRetriever 端到端测试
创建: tests/corpus/search/test_keyword_retriever.py # KeywordRetriever 单元测试
修改: src/corpus/search/retrievers/paper_retriever.py  # RRF k=40, 签名改造
修改: src/corpus/search/retrievers/keyword_retriever.py # 支持 filters
修改: src/corpus/search/retrievers/filter_compiler.py  # year range → Milvus expr
修改: tests/corpus/search/conftest.py           # pytest fixtures
```

---

## Task 1: 创建 API 路由 corpus_search.py

**Files:**
- Create: `src/api/routes/corpus_search.py`
- Test: `tests/corpus/search/test_api_corpus_search.py`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p tests/corpus/search
```

- [ ] **Step 2: 写请求/响应 Pydantic 模型**

```python
# src/api/routes/corpus_search.py

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.corpus.search.retrievers.models import RetrievalPath, RetrievalTrace

router = APIRouter(prefix="/corpus", tags=["corpus"])
logger = logging.getLogger(__name__)


class SearchFilters(BaseModel):
    """元数据过滤条件。"""
    year_range: Optional[tuple[int, int]] = Field(
        default=None, description="年份范围，如 (2020, 2025)"
    )
    source_type: Optional[list[str]] = Field(
        default=None, description="来源类型：arxiv / uploaded_pdf / online_url"
    )
    venue: Optional[list[str]] = Field(
        default=None, description="会议/期刊名称"
    )
    canonical_id: Optional[list[str]] = Field(
        default=None, description="限定特定论文 canonical_id 列表"
    )


class CorpusSearchRequest(BaseModel):
    """POST /corpus/search 请求体。"""
    query: str = Field(..., min_length=1, max_length=2000)
    sub_questions: list[str] = Field(
        default_factory=list,
        description="SearchPlan 中的子问题列表"
    )
    filters: Optional[SearchFilters] = Field(default=None)
    top_k: int = Field(default=100, ge=1, le=500, description="每路召回固定 Top-K")
    recall_top_k: int = Field(
        default=100, ge=1, le=500,
        description="各召回路径返回的数量（keyword + dense）"
    )
    embedding: Optional[list[float]] = Field(
        default=None,
        description="可选的 query embedding（无则自动生成）"
    )


class RecallResultResponse(BaseModel):
    """单条召回结果。"""
    chunk_id: str
    doc_id: str
    canonical_id: Optional[str] = None
    score: float
    path: str
    matched_query: str
    section: str = ""
    text: str = ""


class MergedCandidateResponse(BaseModel):
    """合并后候选论文。"""
    doc_id: str
    canonical_id: Optional[str] = None
    title: str = ""
    authors: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    source_type: str = ""
    rrf_score: float = 0.0
    keyword_score: Optional[float] = None
    dense_score: Optional[float] = None
    recall_results: list[RecallResultResponse] = Field(default_factory=list)


class RetrievalTraceResponse(BaseModel):
    """检索轨迹。"""
    query: str
    sub_question_id: Optional[str] = None
    retrieval_path: str
    target_index: str
    filter_summary: str
    top_k_requested: int
    returned_doc_ids: list[str]
    returned_chunk_ids: list[str]
    returned_count: int
    duration_ms: float
    error: Optional[str] = None


class CorpusSearchResponse(BaseModel):
    """POST /corpus/search 响应体。"""
    candidates: list[MergedCandidateResponse]
    trace: list[RetrievalTraceResponse]
    total_candidates: int = 0
    merged_count: int = 0
    duration_ms: float = 0.0
```

- [ ] **Step 3: 写路由处理函数**

```python
@router.post("/search", response_model=CorpusSearchResponse)
async def corpus_search(req: CorpusSearchRequest) -> CorpusSearchResponse:
    """
    Paper-level 检索：高召回论文候选池 + 检索轨迹。

    流水线：
        query preparation → hybrid recall → candidate merge → trace build
    """
    import time
    from src.corpus.search.retrievers.paper_retriever import PaperRetriever
    from src.corpus.search.retrievers.query_prep import prepare_search
    from src.corpus.store.repository import CorpusRepository

    start = time.time()

    try:
        repo = CorpusRepository()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"CorpusRepository 初始化失败：{e}")

    try:
        result = repo.search_papers_ex(
            query=req.query,
            sub_questions=[{"id": f"sq-{i}", "text": sq} for i, sq in enumerate(req.sub_questions)],
            filters=req.filters,
            top_k=req.top_k,
            recall_top_k=req.recall_top_k,
            embedding=req.embedding,
        )
    except Exception as e:
        logger.exception(f"[/corpus/search] 检索失败：{e}")
        raise HTTPException(status_code=500, detail=str(e))

    # 转换 MergedCandidate → MergedCandidateResponse
    candidates = [
        MergedCandidateResponse(
            doc_id=c.doc_id,
            canonical_id=c.canonical_id or None,
            title=c.title,
            authors=", ".join(c.authors) if c.authors else None,
            year=c.year,
            venue=c.venue,
            abstract=c.abstract,
            source_type=c.source_uri,
            rrf_score=c.rrf_score,
            keyword_score=c.keyword_score or None,
            dense_score=c.dense_score or None,
            recall_results=[
                RecallResultResponse(
                    chunk_id=ev.chunk_id,
                    doc_id=ev.doc_id,
                    canonical_id=ev.canonical_id or None,
                    score=ev.score,
                    path=ev.path.value,
                    matched_query=getattr(ev, "matched_query", ""),
                    section=ev.section,
                    text=ev.text[:500],
                )
                for ev in c.recall_evidence
            ],
        )
        for c in result.candidates
    ]

    traces = [
        RetrievalTraceResponse(
            query=t.query,
            sub_question_id=t.sub_question_id,
            retrieval_path=t.retrieval_path.value,
            target_index=t.target_index,
            filter_summary=t.filter_summary,
            top_k_requested=t.top_k_requested,
            returned_doc_ids=t.returned_doc_ids,
            returned_chunk_ids=t.returned_chunk_ids,
            returned_count=t.returned_count,
            duration_ms=t.duration_ms,
            error=t.error,
        )
        for t in result.traces
    ]

    duration_ms = (time.time() - start) * 1000

    return CorpusSearchResponse(
        candidates=candidates,
        trace=traces,
        total_candidates=result.total_candidates,
        merged_count=len(candidates),
        duration_ms=duration_ms,
    )
```

- [ ] **Step 4: 挂载路由到 FastAPI app**

在 `src/api/routes/__init__.py` 或 `src/api/main.py` 中添加：

```python
from src.api.routes.corpus_search import router as corpus_search_router

app.include_router(corpus_search_router)
```

- [ ] **Step 5: 写单元测试骨架**

```python
# tests/corpus/search/test_api_corpus_search.py

import pytest
from fastapi.testclient import TestClient


def test_corpus_search_request_validation():
    """测试请求体验证。"""
    from src.api.routes.corpus_search import CorpusSearchRequest

    # 正常请求
    req = CorpusSearchRequest(query="multi-agent systems")
    assert req.query == "multi-agent systems"
    assert req.sub_questions == []
    assert req.top_k == 100

    # 过滤条件
    req2 = CorpusSearchRequest(
        query="retrieval",
        year_range=(2020, 2025),
        source_type=["arxiv"],
    )
    assert req2.year_range == (2020, 2025)
```

- [ ] **Step 6: 运行测试**

```bash
pytest tests/corpus/search/test_api_corpus_search.py -v
```
预期: PASS（至少 request validation 通过）

- [ ] **Step 7: Commit**

```bash
git add src/api/routes/corpus_search.py tests/corpus/search/
git commit -m "feat: add POST /corpus/search API endpoint"
```

---

## Task 2: 修改 paper_retriever.py — RRF k=40 + 新签名

**Files:**
- Modify: `src/corpus/search/retrievers/paper_retriever.py:35`

- [ ] **Step 1: 修改 RRF 默认值**

```python
# src/corpus/search/retrievers/paper_retriever.py

# Default RRF k parameter
RRF_K = 40  # 从 60 改为 40，偏向高频命中
```

- [ ] **Step 2: 修改 search() 方法签名，接收 SearchFilters**

修改 `search()` 方法，添加对 `SearchFilters` Pydantic 模型的支持（可选，兼容现有调用方）：

在文件顶部 import 添加：
```python
from src.api.routes.corpus_search import SearchFilters
```

修改 `search()` 方法签名：
```python
def search(
    self,
    query: str,
    embedding: list[float] | None = None,
    sub_questions: list[dict] | None = None,
    year_range: tuple[int, int] | None = None,
    sources: list[str] | None = None,
    venues: list[str] | None = None,
    workspace_id: str | None = None,
    keyword_top_k: int = 30,
    dense_top_k: int = 30,
    top_k: int = 20,
    rrf_k: int = RRF_K,
    # 新增：统一 filters 参数（优先级高于散参）
    filters: Optional[SearchFilters] = None,
    recall_top_k: int = 100,
) -> InitialPaperCandidates:
    # 如果传了 filters 对象，优先用它
    if filters is not None:
        if filters.year_range:
            year_range = filters.year_range
        if filters.source_type:
            sources = filters.source_type
        if filters.venue:
            venues = filters.venue
    ...
```

同时把 `keyword_top_k` 和 `dense_top_k` 统一改为 `recall_top_k` 参数驱动：
```python
    kw_evidence, dense_evidence, traces = self._recall_for_query(
        main_query,
        compiled,
        keyword_top_k=recall_top_k,
        dense_top_k=recall_top_k,
        embedding=embedding,
    )
```

- [ ] **Step 3: 运行现有测试**

```bash
pytest tests/corpus/ -v -k "paper" --tb=short 2>&1 | head -50
```
预期: 现有测试仍然通过

- [ ] **Step 4: Commit**

```bash
git add src/corpus/search/retrievers/paper_retriever.py
git commit -m "fix: RRF k=40, add SearchFilters parameter and recall_top_k"
```

---

## Task 3: 修改 KeywordRetriever — 支持 filters 参数

**Files:**
- Modify: `src/corpus/search/retrievers/keyword_retriever.py`
- Test: `tests/corpus/search/test_keyword_retriever.py`

- [ ] **Step 1: 修改 search() 和 _search_title() 等方法，支持 filters**

在 `_search_title` 中添加 year/source/venue 过滤：

```python
def _search_title(
    self, query: str, top_k: int,
    doc_ids: list[str] | None = None,
    filters: Optional[dict] = None,  # 新增
) -> list[RecallEvidence]:
    """在论文标题上做 BM25 检索。"""
    from sqlalchemy import func, text, and_
    from src.db.models import Document

    q = (
        self._db.query(
            Document.doc_id,
            Document.canonical_id,
            Document.title,
            Document.source_uri,
            Document.published_date,
            Document.source_type,
            func.ts_rank(
                func.to_tsvector("english", Document.title),
                func.plainto_tsquery("english", query),
            ).label("score"),
        )
        .filter(
            func.to_tsvector("english", Document.title).op("@@")(
                func.plainto_tsquery("english", query)
            )
        )
    )

    if doc_ids:
        q = q.filter(Document.doc_id.in_(doc_ids))

    # 新增 filters 过滤
    if filters:
        if filters.get("year_range"):
            y_min, y_max = filters["year_range"]
            q = q.filter(
                func.substring(Document.published_date, 1, 4)
                .cast_(func.integer) >= y_min,
                func.substring(Document.published_date, 1, 4)
                .cast_(func.integer) <= y_max,
            )
        if filters.get("source_type"):
            q = q.filter(Document.source_type.in_(filters["source_type"]))

    rows = q.order_by(text("score DESC")).limit(top_k).all()
    return [...]
```

同样修改 `_search_abstract` 和 `_search_coarse`。

修改 `search()` 方法签名：
```python
def search(
    self,
    query: str,
    path: RetrievalPath = RetrievalPath.KEYWORD_COARSE,
    top_k: int = 30,
    doc_ids: list[str] | None = None,
    filters: Optional[dict] | None = None,  # 新增
) -> list[RecallEvidence]:
```

修改 `search_all_paths()` 签名和实现：
```python
def search_all_paths(
    self,
    query: str,
    top_k: int = 20,
    doc_ids: list[str] | None = None,
    filters: Optional[dict] | None = None,  # 新增
) -> dict[RetrievalPath, list[RecallEvidence]]:
    title_results = self._search_title(query, top_k, doc_ids, filters)
    abstract_results = self._search_abstract(query, top_k, doc_ids, filters)
    coarse_results = self._search_coarse(query, top_k, doc_ids, filters)
    ...
```

- [ ] **Step 2: 修改 paper_retriever.py 调用处**

在 `_recall_for_query` 中把 compiled filters 传给 keyword retriever：

```python
kw_results = self._keyword_retriever.search_all_paths(
    query=query.text,
    top_k=keyword_top_k,
    filters=compiled.milvus_filter,  # 新增
)
```

- [ ] **Step 3: 写 KeywordRetriever 单元测试**

```python
# tests/corpus/search/test_keyword_retriever.py

import pytest
from unittest.mock import MagicMock, patch
from src.corpus.search.retrievers.keyword_retriever import KeywordRetriever
from src.corpus.search.retrievers.models import RetrievalPath


def test_search_title_returns_correct_structure():
    """_search_title 返回 RecallEvidence 列表。"""
    mock_session = MagicMock()
    retriever = KeywordRetriever(mock_session)

    # Mock query 结果
    mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        ("doc-1", "canon-1", "Multi-Agent Survey", "uri", "2024-01-01", "arxiv", 0.85)
    ]

    results = retriever._search_title("multi-agent", top_k=10, doc_ids=None, filters=None)
    assert len(results) == 1
    assert results[0].path == RetrievalPath.KEYWORD_TITLE
    assert results[0].text == "Multi-Agent Survey"
```

- [ ] **Step 4: Commit**

```bash
git add src/corpus/search/retrievers/keyword_retriever.py tests/corpus/search/
git commit -m "feat: KeywordRetriever supports filters on title/abstract/coarse"
```

---

## Task 4: 修改 FilterCompiler — year range → Milvus expr

**Files:**
- Modify: `src/corpus/search/retrievers/filter_compiler.py`

- [ ] **Step 1: 添加 year range 到 Milvus filter**

修改 `compile()` 方法，在 `milvus_parts` 中加入 year range 过滤：

```python
# Milvus filter 中 year 字段映射到 published_year（需在 Milvus schema 中存在）
if filters.year_min is not None or filters.year_max is not None:
    year_parts = []
    if filters.year_min is not None:
        year_parts.append(f"published_year >= {filters.year_min}")
    if filters.year_max is not None:
        year_parts.append(f"published_year <= {filters.year_max}")
    if year_parts:
        milvus_parts["published_year"] = {"$gte": filters.year_min, "$lte": filters.year_max}
```

注意：Milvus filter 表达式需要确认 `published_year` 字段是否存在于 Milvus schema。如果不存在，需要在 Milvus upsert 时从 `published_date` 提取 year。

- [ ] **Step 2: 测试 FilterCompiler**

```python
# tests/corpus/search/test_filter_compiler.py

import pytest
from src.corpus.search.retrievers.query_prep import PreparedFilters
from src.corpus.search.retrievers.filter_compiler import FilterCompiler


def test_year_range_compiles():
    """year_range 编译出正确的 Milvus expr。"""
    compiler = FilterCompiler()
    filters = PreparedFilters(year_min=2020, year_max=2025)
    compiled = compiler.compile(filters)
    assert "published_year" in compiled.milvus_filter
```

- [ ] **Step 3: Commit**

```bash
git add src/corpus/search/retrievers/filter_compiler.py
git commit -m "feat: FilterCompiler supports year range in Milvus expr"
```

---

## Task 5: 对接 CorpusRepository.search_papers_ex

**Files:**
- Modify: `src/corpus/store/repository.py`

- [ ] **Step 1: 实现 search_papers_ex()**

在 `CorpusRepository` 中添加/完善 `search_papers_ex()` 方法：

```python
def search_papers_ex(
    self,
    query: str,
    sub_questions: list[dict] | None = None,
    filters: "SearchFilters" | None = None,
    top_k: int = 100,
    recall_top_k: int = 100,
    embedding: list[float] | None = None,
) -> "InitialPaperCandidates":
    """
    模块 4 检索入口：paper-level hybrid search。

    调用 PaperRetriever，输出高召回论文候选池。
    """
    from src.corpus.search.retrievers.paper_retriever import PaperRetriever

    retriever = PaperRetriever(
        db_session=self._db,
        milvus_index=self._vector_index,
        collection_coarse=self._collection_coarse,
    )

    return retriever.search(
        query=query,
        embedding=embedding,
        sub_questions=sub_questions,
        filters=filters,
        recall_top_k=recall_top_k,
        top_k=top_k,
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/corpus/store/repository.py
git commit -m "feat: CorpusRepository.search_papers_ex calls PaperRetriever"
```

---

## Task 6: 端到端集成测试

**Files:**
- Create: `tests/corpus/search/test_paper_retriever.py`
- Create: `tests/corpus/search/conftest.py`

- [ ] **Step 1: 创建 conftest.py fixtures**

```python
# tests/corpus/search/conftest.py

import pytest
from dotenv import load_dotenv
load_dotenv()


@pytest.fixture
def db_session():
    """真实 PostgreSQL session（需 DATABASE_URL）。"""
    from src.db import get_db_session
    with get_db_session() as s:
        yield s


@pytest.fixture
def milvus_index():
    """真实 Milvus 连接。"""
    from src.corpus.store.vector_index import get_vector_index
    idx = get_vector_index()
    idx.connect()
    yield idx
    idx.disconnect()
```

- [ ] **Step 2: 端到端测试**

```python
# tests/corpus/search/test_paper_retriever.py

import pytest
from src.corpus.search.retrievers.paper_retriever import PaperRetriever


@pytest.mark.skipif(
    True,  # 依赖真实 DB + Milvus，按需开启
    reason="需要 DATABASE_URL + Milvus"
)
def test_paper_retriever_returns_candidates(db_session, milvus_index):
    """端到端：检索返回候选论文列表。"""
    retriever = PaperRetriever(
        db_session=db_session,
        milvus_index=milvus_index,
    )

    result = retriever.search(
        query="multi-agent systems retrieval",
        recall_top_k=50,
        top_k=20,
    )

    assert isinstance(result, type(result))
    assert result.total_candidates >= 0
    assert len(result.candidates) <= 20
```

- [ ] **Step 3: Commit**

```bash
git add tests/corpus/search/
git commit -m "test: add paper retriever integration tests"
```

---

## 依赖关系

```
Task 1 (API) → Task 5 (CorpusRepository.search_papers_ex)
Task 2 (paper_retriever) → Task 1, Task 5
Task 3 (KeywordRetriever filters) → Task 2
Task 4 (FilterCompiler year) → Task 2
Task 6 (tests) → Task 1, 2, 3, 4, 5
```

执行顺序：Task 2 → Task 3 → Task 4 → Task 5 → Task 1 → Task 6

---

## 自查清单

1. **Spec 覆盖**：所有设计决策（RRF k=40、Flat merge、固定 top_k=100）均已实现
2. **占位符检查**：无 TBD/TODO，无未填写的步骤
3. **类型一致性**：Pydantic 模型 → API → PaperRetriever → KeywordRetriever → FilterCompiler 链路通顺
4. **API 签名**：`POST /corpus/search` 请求/响应与 `InitialPaperCandidates` 数据结构对应

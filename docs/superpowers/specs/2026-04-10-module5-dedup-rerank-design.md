# 模块 5：Dedup + Rerank 设计方案

**日期**: 2026-04-10
**状态**: 已批准
**负责人**: PaperReader Agent

---

## 1. 核心定位

模块 5 负责将模块 4 输出的"多路粗召回候选池"收束成"去重且精排后的高质量 Top-K 论文候选"。

```
InitialPaperCandidates（模块 4）
        ↓
Canonical Dedup（按 canonical_id 归并）
        ↓
Recall Fusion（RRF 融合）
        ↓
Cohere Rerank（Top-M 进入精排）
        ↓
Top-K PaperCandidate
```

---

## 2. 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Dedup 维度 | canonical_id | 将同一论文的多来源版本（PDF/arXiv/conference）归并为单一候选 |
| Fusion 方式 | RRF（k=40，沿用模块 4） | 已在 CandidateMerger 中实现 |
| Reranker | Cohere Rerank API | 效果稳定、接入简单、排序质量优于本地轻量模型 |
| API 形式 | 集成到 POST /corpus/search | 模块 4+5 一体化，一次调用返回完整结果 |
| Rerank 预算 | Top-M（M 可配置，默认 50） | cross-encoder 比 recall 贵，不对全量候选跑 |

---

## 3. API 修改

### 修改 `POST /corpus/search` 请求体

在 `CorpusSearchRequest` 中新增 rerank 参数：

```python
class CorpusSearchRequest(BaseModel):
    query: str
    sub_questions: list[str] = []
    filters: Optional[SearchFilters] = None
    top_k: int = Field(default=100, ge=1, le=500)     # 最终返回数量
    recall_top_k: int = Field(default=100, ge=1, le=500)  # 各路召回数量
    # 模块 5 新增参数
    enable_rerank: bool = Field(default=True, description="是否启用 Cohere Rerank")
    rerank_top_m: int = Field(
        default=50, ge=5, le=200,
        description="进入 rerank 的候选数量"
    )
    rerank_model: str = Field(
        default="rerank-multilingual-v2.0",
        description="Cohere rerank 模型名"
    )
    embedding: Optional[list[float]] = None
```

### 响应体

沿用现有的 `CorpusSearchResponse`，其中 `MergedCandidateResponse` 新增 rerank 字段：

```python
class MergedCandidateResponse(BaseModel):
    doc_id: str
    canonical_id: Optional[str] = None
    title: str = ""
    authors: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    source_type: str = ""
    # 模块 4 分数
    rrf_score: float = 0.0
    keyword_score: Optional[float] = None
    dense_score: Optional[float] = None
    # 模块 5 新增分数
    rerank_score: Optional[float] = None  # Cohere 返回的相关性分数
    final_score: float = 0.0             # 最终排序分数（可配置：仅 rerank 或 hybrid）
    # 来源追踪
    recall_results: list[RecallResultResponse] = []
    # 去重信息
    dedup_info: Optional[DedupInfo] = None


class DedupInfo(BaseModel):
    """去重信息。"""
    is_canonical_representative: bool = True  # 是否是该 canonical_id 的主版本
    merged_doc_ids: list[str] = []           # 被归并到同一 canonical_id 的其他 doc_ids
    source_refs: list[str] = []               # 所有来源
```

---

## 4. Canonical Dedup 实现

### 4.1 当前状态

`CandidateMerger.merge()` 目前按 `doc_id` 去重，同一篇论文的多个版本（PDF / arXiv / conference）会被作为不同候选。

### 4.2 改造方案

**新增文件**: `src/corpus/search/deduper.py`

```python
class PaperDeduper:
    """
    Canonical Dedup：对候选池按 canonical_id 做论文级归并。

    同一论文的不同来源（PDF / arXiv / conference / journal）合并为单一候选。
    """

    def __init__(self, db_session: "Session"):
        self._db = db_session

    def dedup(
        self,
        candidates: list[MergedCandidate],
    ) -> list[DedupedCandidate]:
        """
        对候选列表做 canonical dedup。

        Args:
            candidates: 模块 4 输出的 MergedCandidate 列表

        Returns:
            DedupedCandidate 列表（按 canonical_id 归并）
        """
        # 1. 按 canonical_id 分组（None 的保留独立条目）
        groups: dict[str, list[MergedCandidate]] = {}
        for c in candidates:
            key = c.canonical_id or c.doc_id  # 无 canonical_id 则用 doc_id
            groups.setdefault(key, []).append(c)

        # 2. 对每个 group 做聚合
        deduped: list[DedupedCandidate] = []
        for key, group in groups.items():
            deduped.append(self._merge_group(group))

        return deduped

    def _merge_group(
        self, group: list[MergedCandidate]
    ) -> DedupedCandidate:
        """
        将同一 canonical_id 下的多条候选合并为一条 DedupedCandidate。

        合并策略：
        - 选择 RRF score 最高的候选作为主候选（canonical_representative）
        - 收集所有 source_refs
        - 收集所有 matched_queries（去重）
        - 收集所有 recall_paths
        - 聚合 keyword_score / dense_score（取各路最高分）
        - 收集所有 recall_evidence（合并）
        """
        # 选主候选（RRF 分数最高的那个）
        primary = max(group, key=lambda c: c.rrf_score)

        deduped = DedupedCandidate(
            canonical_id=primary.canonical_id or primary.doc_id,
            merged_doc_ids=[c.doc_id for c in group],
            primary_doc_id=primary.doc_id,
            # 元数据（取主候选的）
            title=primary.title,
            abstract=primary.abstract,
            authors=primary.authors,
            year=primary.year,
            venue=primary.venue,
            # 分数（各路取最高）
            rrf_score=primary.rrf_score,
            keyword_score=max((c.keyword_score for c in group), default=0.0),
            dense_score=max((c.dense_score for c in group), default=0.0),
            # 来源追踪
            matched_queries=[],       # 去重后填充
            matched_paths=[],         # 去重后填充
            recall_evidence=[],        # 合并后填充
            # 去重信息
            dedup_info=DedupInfo(
                is_canonical_representative=True,
                merged_doc_ids=[c.doc_id for c in group if c.doc_id != primary.doc_id],
                source_refs=self._collect_source_refs(group),
            ),
        )

        # 合并 matched_queries（去重）
        seen_queries = set()
        for c in group:
            for mq in c.matched_queries:
                key = (mq.query_text, mq.path.value)
                if key not in seen_queries:
                    deduped.matched_queries.append(mq)
                    seen_queries.add(key)

        # 合并 matched_paths
        deduped.matched_paths = list(set(
            mq.path for c in group for mq in c.matched_queries
        ))

        # 合并 recall_evidence（取每个 path 最优的 top-N）
        deduped.recall_evidence = self._merge_evidence(group, top_n=3)

        return deduped

    def _merge_evidence(
        self,
        group: list[MergedCandidate],
        top_n: int = 3,
    ) -> list[RecallEvidence]:
        """从 group 中收集最好的 recall evidence（每个 path 取 top-N）。"""
        from collections import defaultdict
        by_path: dict[RetrievalPath, list[RecallEvidence]] = defaultdict(list)
        for c in group:
            for ev in c.recall_evidence:
                by_path[ev.path].append(ev)

        merged = []
        for path, evs in by_path.items():
            top_evs = sorted(evs, key=lambda e: e.score, reverse=True)[:top_n]
            merged.extend(top_evs)
        return merged

    def _collect_source_refs(
        self, group: list[MergedCandidate]
    ) -> list[str]:
        """收集所有来源 URI。"""
        refs = []
        for c in group:
            if c.source_uri:
                refs.append(c.source_uri)
        return refs
```

### 4.3 DedupedCandidate 数据模型

```python
@dataclass
class DedupedCandidate:
    """去重后的单篇论文候选（canonical dedup 后的中间格式）。"""

    canonical_id: str
    merged_doc_ids: list[str]          # 被归并的所有 doc_ids
    primary_doc_id: str                 # 代表性 doc_id

    # 元数据
    title: str = ""
    abstract: Optional[str] = None
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None

    # 模块 4 分数（RRF 融合后）
    rrf_score: float = 0.0
    keyword_score: float = 0.0
    dense_score: float = 0.0

    # 来源追踪
    matched_queries: list[MatchedQuery] = field(default_factory=list)
    matched_paths: list[RetrievalPath] = field(default_factory=list)
    recall_evidence: list[RecallEvidence] = field(default_factory=list)

    # 去重信息
    dedup_info: DedupInfo = field(default_factory=DedupInfo)

    # 模块 5 Rerank 分数
    rerank_score: Optional[float] = None
    final_score: float = 0.0
```

---

## 5. Fusion 实现

Fusion 沿用模块 4 的 RRF 结果（`CandidateMerger.merge()` 已实现），在 dedup 后不需要再做额外 fusion。DedupedCandidate 的 `rrf_score` 即为融合分数。

**Rerank Budget 截断**：
```python
rerank_pool = sorted(deduped, key=lambda c: c.rrf_score, reverse=True)[:rerank_top_m]
```

---

## 6. Reranker 实现

### 6.1 新增文件

**文件**: `src/corpus/search/reranker.py`

```python
"""Cohere Reranker — 对候选论文做语义重排。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import cohere

from src.corpus.search.deduper import DedupedCandidate

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """单条 rerank 结果。"""
    doc_id: str
    canonical_id: str
    rerank_score: float     # Cohere 返回的相关性分数
    rerank_index: int      # 在 Cohere 返回列表中的位置


class CohereReranker:
    """
    Cohere Rerank API 封装。

    支持模型：rerank-multilingual-v2.0
    文档：https://docs.cohere.com/reference/rerank
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Cohere API Key（从环境变量 COHERE_API_KEY 读取）
        """
        self._api_key = api_key or os.getenv("COHERE_API_KEY")
        self._client: Optional[cohere.Client] = None

    def _get_client(self) -> cohere.Client:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "COHERE_API_KEY 未配置。"
                    "请设置环境变量或在初始化时传入 api_key。"
                )
            self._client = cohere.Client(self._api_key)
        return self._client

    def rerank(
        self,
        query: str,
        candidates: list[DedupedCandidate],
        model: str = "rerank-multilingual-v2.0",
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """
        对候选论文做 Cohere Rerank。

        Args:
            query: 检索 query
            candidates: 待重排的候选（通常为 RRF 截断后的 Top-M）
            model: Cohere rerank 模型名
            top_n: 返回多少条（None = 返回全部）

        Returns:
            RerankResult 列表（按 rerank_score 降序）
        """
        if not candidates:
            return []

        if not self._api_key:
            logger.warning("[CohereReranker] 未配置 COHERE_API_KEY，跳过 rerank")
            return []

        # 构造 rerank 文档（Cohere 接受 list[str]）
        # 取 title 作为主要文本，abstract 作为补充
        docs = []
        for c in candidates:
            text_parts = [c.title]
            if c.abstract:
                text_parts.append(c.abstract)
            docs.append("\n".join(text_parts))

        try:
            client = self._get_client()
            response = client.rerank(
                query=query,
                documents=docs,
                model=model,
                top_n=top_n,
                return_documents=False,
            )

            results: list[RerankResult] = []
            for result in response.results:
                idx = result.index
                doc_id = candidates[idx].primary_doc_id
                results.append(RerankResult(
                    doc_id=doc_id,
                    canonical_id=candidates[idx].canonical_id,
                    rerank_score=result.relevance_score,
                    rerank_index=result.index,
                ))

            logger.info(
                f"[CohereReranker] query='{query[:30]}' "
                f"candidates={len(candidates)} returned={len(results)}"
            )
            return results

        except Exception as e:
            logger.error(f"[CohereReranker] rerank 失败：{e}")
            return []

    def rerank_with_fusion(
        self,
        query: str,
        candidates: list[DedupedCandidate],
        fusion_weights: tuple[float, float] = (0.4, 0.6),
        model: str = "rerank-multilingual-v2.0",
        top_n: int | None = None,
    ) -> list[DedupedCandidate]:
        """
        Rerank 并与 RRF 分数做加权融合。

        Args:
            fusion_weights: (rrf_weight, rerank_weight)，默认 (0.4, 0.6)
                            即 60% 依赖 rerank 分数，40% 保留 recall 信号
        """
        rrf_weight, rerank_weight = fusion_weights

        # 归一化 RRF 分数
        max_rrf = max((c.rrf_score for c in candidates), default=1.0)
        rrf_normalized = {c.canonical_id: c.rrf_score / max_rrf for c in candidates}

        # Cohere rerank
        rerank_results = self.rerank(query, candidates, model=model, top_n=top_n)
        if not rerank_results:
            # Rerank 失败时退化为纯 RRF 排序
            return sorted(candidates, key=lambda c: c.rrf_score, reverse=True)

        # 归一化 rerank 分数（Cohere 0-1 范围）
        rerank_normalized = {r.canonical_id: r.rerank_score for r in rerank_results}

        # 加权融合
        for c in candidates:
            rrf_n = rrf_normalized.get(c.canonical_id, 0.0)
            rerank_n = rerank_normalized.get(c.canonical_id, 0.0)
            c.final_score = rrf_weight * rrf_n + rerank_weight * rerank_n
            c.rerank_score = rerank_n

        return sorted(candidates, key=lambda c: c.final_score, reverse=True)
```

### 6.2 环境变量配置

在 `.env.example` 中添加：

```bash
COHERE_API_KEY=your_cohere_api_key_here
```

---

## 7. Candidate Builder 实现

### 7.1 新增文件

**文件**: `src/corpus/search/candidate_builder.py`

```python
"""Candidate Builder — 构建最终 Top-K PaperCandidate。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScoreBreakdown:
    """分数明细。"""
    rrf_score: float = 0.0
    keyword_score: float = 0.0
    dense_score: float = 0.0
    rerank_score: Optional[float] = None
    final_score: float = 0.0


@dataclass
class PaperCandidate:
    """
    最终论文候选（模块 5 输出）。

    这是系统内用于后续 workflow 的标准论文候选格式。
    """
    paper_id: str                    # 等于 primary_doc_id
    canonical_id: str
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None

    # 来源
    source_refs: list[str] = field(default_factory=list)  # 所有版本来源
    primary_doc_id: str = ""          # 代表性版本

    # 分数
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)

    # 追踪
    matched_queries: list[str] = field(default_factory=list)   # 命中的查询
    matched_paths: list[str] = field(default_factory=list)     # 命中的召回路
    why_retrieved: str = ""           # 简短描述为什么被召回


class CandidateBuilder:
    """将 DedupedCandidate 转换为 PaperCandidate。"""

    def build(
        self,
        deduped: list[DedupedCandidate],
        top_k: int = 20,
    ) -> list[PaperCandidate]:
        """
        构建最终 Top-K PaperCandidate。

        Args:
            deduped: 去重后的候选列表
            top_k: 返回数量

        Returns:
            Top-K PaperCandidate 列表
        """
        # 按 final_score 降序排列
        sorted_candidates = sorted(
            deduped, key=lambda c: c.final_score, reverse=True
        )[:top_k]

        return [self._to_paper_candidate(c) for c in sorted_candidates]

    def _to_paper_candidate(self, c: DedupedCandidate) -> PaperCandidate:
        """将 DedupedCandidate 转换为 PaperCandidate。"""
        return PaperCandidate(
            paper_id=c.primary_doc_id,
            canonical_id=c.canonical_id,
            title=c.title,
            authors=c.authors,
            year=c.year,
            venue=c.venue,
            abstract=c.abstract,
            source_refs=c.dedup_info.source_refs,
            primary_doc_id=c.primary_doc_id,
            scores=ScoreBreakdown(
                rrf_score=c.rrf_score,
                keyword_score=c.keyword_score,
                dense_score=c.dense_score,
                rerank_score=c.rerank_score,
                final_score=c.final_score or c.rrf_score,
            ),
            matched_queries=[mq.query_text for mq in c.matched_queries],
            matched_paths=[p.value for p in c.matched_paths],
            why_retrieved=self._build_why(c),
        )

    def _build_why(self, c: DedupedCandidate) -> str:
        """生成 why_retrieved 描述。"""
        paths = [p.value for p in c.matched_paths]
        path_str = ", ".join(paths) if paths else "unknown"
        return f"Matched via {path_str} (RRF={c.rrf_score:.3f})"
```

---

## 8. 端到端流水线

```
POST /corpus/search
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  Phase 1: 模块 4 — Paper-level Retrieval            │
│  CorpusRepository.search_papers_ex()                 │
│  PaperRetriever.search()                            │
│  KeywordRetriever + DenseRetriever                  │
│  CandidateMerger.merge() → InitialPaperCandidates   │
└─────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  Phase 2: 模块 5 — Dedup + Rerank                   │
│                                                     │
│  1. PaperDeduper.dedup(candidates)                  │
│     → List[DedupedCandidate]                        │
│                                                     │
│  2. RRF Budget Trim                                 │
│     → Top-M 进入 rerank pool                        │
│                                                     │
│  3. CohereReranker.rerank_with_fusion()            │
│     → RRF × Cohere 加权融合                        │
│     → final_score                                   │
│                                                     │
│  4. CandidateBuilder.build()                        │
│     → Top-K PaperCandidate                          │
└─────────────────────────────────────────────────────┘
      │
      ▼
CorpusSearchResponse(candidates: list[PaperCandidate])
```

---

## 9. 文件结构

```
src/corpus/search/
├── __init__.py
├── retrievers/
│   └── ... (模块 4 已完成)
├── deduper.py               # 新增：Canonical Dedup
├── reranker.py              # 新增：Cohere Rerank
└── candidate_builder.py     # 新增：构建 PaperCandidate

src/api/routes/
└── corpus_search.py         # 修改：集成模块 5

.env.example                  # 修改：添加 COHERE_API_KEY

tests/corpus/search/
└── test_deduper.py          # 新增
└── test_reranker.py         # 新增
```

---

## 10. 关键实现细节

### 10.1 Dedup 时保留哪条元数据

当同一 canonical_id 下有多条候选时，**元数据（title/authors/year/venue）以 RRF 分数最高的那条为准**（primary candidate）。这是因为 RRF 分数最高意味着该版本的文本（PDF/arXiv/conference）与 query 最相关。

### 10.2 Rerank 输入文本构造

Cohere Rerank 接受每篇论文一个文档字符串。Cohere 官方推荐将标题放在最前面：

```
{title}
{abstract}
```

不要把所有 matched chunks 全部塞进去，避免上下文稀释。

### 10.3 Fusion 权重

`(rrf=0.4, rerank=0.6)` 是保守起点，理由：
- Rerank 分数更准，给更高权重
- 保留 40% recall 信号，避免 rerank 结果和原始 query 偏离太远

后续可通过模块 7（evals）实验调参。

### 10.4 Rerank 失败降级

如果 `COHERE_API_KEY` 未配置或 Cohere 调用失败，退化为纯 RRF 排序，不阻塞主流程。

---

## 11. 测试策略

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_deduper.py` | dedup 按 canonical_id 归并、多来源聚合、元数据合并 |
| `test_reranker.py` | Cohere API mock、rerank_with_fusion 融合逻辑、退化逻辑 |
| `test_candidate_builder.py` | DedupedCandidate → PaperCandidate 转换 |
| `test_api_corpus_search.py` | 修改后的 API 请求/响应（新增 rerank 字段） |

---

## 12. 与现有代码的关系

- **复用**：`CandidateMerger` 的 RRF 实现不变
- **扩展**：`MergedCandidate` 增加 `dedup_info` 和 rerank 相关字段
- **不重复**：不创建独立路由，集成到现有 `POST /corpus/search`
- **模块 5 衔接**：输出 `Top-K PaperCandidate` 直接送入 `select_papers`、`extract_cards`、模块 6（evidence retrieval）

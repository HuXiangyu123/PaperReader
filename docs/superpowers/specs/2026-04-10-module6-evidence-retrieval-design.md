# 模块 6：Chunk-level Evidence Retrieval + RagResult Builder 设计方案

**日期**: 2026-04-10
**状态**: 已批准
**负责人**: PaperReader Agent

---

## 1. 核心定位

模块 6 将"去重排好序的论文候选"变成"可验证、可抽取、可写作"的结构化证据对象。

```
Top-K PaperCandidate
        ↓
Scope Restriction（仅在已选论文内检索）
        ↓
Fine Chunk Recall（keyword + dense hybrid）
        ↓
Chunk Rerank（轻量过滤 + section 启发式）
        ↓
Evidence Typing（section-based heuristic 分类）
        ↓
EvidenceChunk[]
        ↓
RagResult Builder
        ↓
Structured RagResult
```

---

## 2. 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Chunk 检索路径 | keyword + dense hybrid | keyword 适合精确术语匹配，dense 适合语义相似 |
| Chunk rerank | 轻量过滤（非 Cross-Encoder） | fine chunk 数量大，Cross-Encoder 成本高 |
| Evidence Typing | section-based heuristic | 速度快、可靠；LLM 分类留作后续增强 |
| API 形式 | 独立端点 POST /corpus/evidence | 独立演进，与 /corpus/search 解耦 |
| RagResult | 增强现有模型 | 扩展现有 `src/models/paper.py` 中的极简 RagResult |

---

## 3. Evidence Typing 策略

### 3.1 支持类型

| 类型 | 说明 | Section 关键词 |
|------|------|--------------|
| `method` | 方法描述 | Method, Approach, Proposed, Architecture, Model |
| `result` | 实验结果 | Result, Experiment, Evaluation, Performance |
| `background` | 背景介绍 | Introduction, Background, Related |
| `limitation` | 局限性讨论 | Limitation, Failure, Weakness |
| `claim_support` | 支持某个 claim | （默认 fallback） |

### 3.2 启发式映射

```python
SUPPORT_TYPE_KEYWORDS = {
    "method": ["method", "approach", "propose", "architecture", "model", "algorithm"],
    "result": ["result", "experiment", "evaluation", "performance", "benchmark", "accuracy"],
    "background": ["introduction", "background", "related work", "survey"],
    "limitation": ["limitation", "weakness", "failure", "cannot", "does not scale"],
}

def infer_support_type(section: str) -> str:
    section_lower = section.lower()
    for stype, keywords in SUPPORT_TYPE_KEYWORDS.items():
        if any(kw in section_lower for kw in keywords):
            return stype
    return "claim_support"
```

---

## 4. ChunkRetriever 实现

### 4.1 数据流

```python
class ChunkRetriever:
    """
    在已选论文内检索 fine chunks。
    支持 keyword + dense hybrid search。
    """

    def __init__(
        self,
        chunk_store: ChunkStore,     # 已有
        vector_store: VectorStore,   # 已有
        embedding_model=None,         # SentenceTransformer，可选
    ):
        ...

    def retrieve(
        self,
        paper_ids: list[str],        # 论文 doc_ids
        query: str,
        sub_questions: list[str] = [],
        top_k_per_paper: int = 10,
        top_k_global: int = 50,
    ) -> list[EvidenceChunk]:
        """
        在指定论文列表内检索 evidence chunks。
        """
        # 1. 收集 fine chunks（来自已选论文）
        all_chunks = self._collect_chunks(paper_ids)

        # 2. 多路检索（keyword + dense）
        keyword_chunks = self._keyword_search(query, all_chunks, top_k=top_k_global)
        dense_chunks  = self._dense_search(query, all_chunks, top_k=top_k_global)

        # 3. 合并（RRF）
        merged_chunks = self._rrf_merge(keyword_chunks, dense_chunks)

        # 4. 过滤（去噪：移除太短/太长/chunk）
        filtered = self._filter_chunks(merged_chunks)

        # 5. 全局截断
        return filtered[:top_k_global]
```

### 4.2 Keyword 检索

```python
def _keyword_search(
    self,
    query: str,
    chunks: list[FineChunk],
    top_k: int,
) -> list[tuple[FineChunk, float]]:
    """BM25 相似度检索（基于 text）。"""
    import rank_bm25
    # tokenize chunks
    # rank BM25 scores
    # return top_k
```

### 4.3 Dense 检索

```python
def _dense_search(
    self,
    query: str,
    chunks: list[FineChunk],
    top_k: int,
) -> list[tuple[FineChunk, float]]:
    """向量相似度检索。"""
    query_embedding = self._embedding_model.encode([query])
    # Milvus ANN search
    # return top_k
```

### 4.4 RRF 合并

```python
def _rrf_merge(
    self,
    keyword_results: list[tuple[FineChunk, float]],
    dense_results: list[tuple[FineChunk, float]],
    k: int = 40,
) -> list[tuple[FineChunk, float]]:
    """Reciprocal Rank Fusion。"""
    scores: dict[str, tuple[float, int, int]] = {}  # chunk_id -> (score, k_rank, d_rank)
    for rank, (chunk, score) in enumerate(keyword_results):
        scores[chunk.chunk_id] = (score, rank + 1, scores.get(chunk.chunk_id, (0, 0, 0))[2])
    for rank, (chunk, score) in enumerate(dense_results):
        key = chunk.chunk_id
        prev = scores.get(key, (0, 0, 0))
        scores[key] = (score, prev[1], rank + 1)
    # compute RRF
    rrf_scores = {
        cid: (1 / (k + kr), 1 / (k + dr))
        for cid, (_, kr, dr) in scores.items()
    }
    # sort and return
```

---

## 5. EvidenceTyper 实现

```python
class EvidenceTyper:
    """
    基于 section name 的轻量 evidence typing。
    速度极快，适合大规模 evidence 标注。
    """

    SUPPORT_TYPE_KEYWORDS = {
        "method": ["method", "approach", "propose", "architecture",
                   "model", "algorithm", "framework"],
        "result": ["result", "experiment", "evaluation", "performance",
                   "benchmark", "accuracy", "accuracy", "score", "dataset"],
        "background": ["introduction", "background", "related work",
                       "survey", "prior", "previous"],
        "limitation": ["limitation", "weakness", "failure", "cannot",
                      "does not scale", "drawback"],
    }

    def type_chunk(self, chunk: FineChunk) -> str:
        """推断单个 chunk 的 support_type。"""
        return self.infer_support_type(chunk.section or "")

    def type_chunks(self, chunks: list[FineChunk]) -> list[str]:
        """批量推断 chunks 的 support_type。"""
        return [self.type_chunk(c) for c in chunks]

    def infer_support_type(self, section: str) -> str:
        section_lower = section.lower()
        for stype, keywords in self.SUPPORT_TYPE_KEYWORDS.items():
            if any(kw in section_lower for kw in keywords):
                return stype
        return "claim_support"
```

---

## 6. EvidenceChunk 模型

```python
@dataclass
class EvidenceChunk:
    """Evidence 检索结果（模块 6 输出）。"""
    chunk_id: str
    paper_id: str              # doc_id
    canonical_id: str = ""

    # 内容
    text: str = ""
    section: str = ""
    page_start: int = 1
    page_end: int = 1

    # 检索分数
    keyword_score: float = 0.0
    dense_score: float = 0.0
    rrf_score: float = 0.0

    # Evidence typing
    support_type: str = "claim_support"  # method/result/background/limitation/claim_support

    # 来源追踪
    matched_query: str = ""
    sub_question_id: str = ""
    chunk_path: str = "keyword"  # keyword / dense / hybrid
```

---

## 7. RagResult 模型（增强）

扩展 `src/models/paper.py` 中的 `RagResult`：

```python
@dataclass
class RagResult:
    """
    结构化 RAG 检索结果（模块 6 输出）。

    替代字符串拼接，作为后续 workflow 的正式 artifact。
    """
    # 检索上下文
    query: str = ""
    sub_questions: list[str] = field(default_factory=list)
    rag_strategy: str = "keyword+dense+rrf"  # 记录本次检索策略

    # 检索对象
    paper_candidates: list = field(default_factory=list)  # PaperCandidate[]
    evidence_chunks: list = field(default_factory=list)   # EvidenceChunk[]

    # 检索轨迹
    retrieval_trace: list = field(default_factory=list)   # RetrievalTrace[]
    dedup_log: list = field(default_factory=list)         # DedupInfo[]
    rerank_log: list = field(default_factory=list)        # RerankLog[]

    # 覆盖度注释
    coverage_notes: list[str] = field(default_factory=list)
    total_papers: int = 0
    total_chunks: int = 0

    # 时间戳
    retrieved_at: str = ""   # ISO format


@dataclass
class RerankLog:
    """Rerank 日志。"""
    stage: str = ""   # "paper_rerank" / "chunk_rerank"
    model: str = ""
    candidates_count: int = 0
    top_k: int = 0
```

---

## 8. RagResultBuilder 实现

```python
class RagResultBuilder:
    """
    将检索结果构建为结构化 RagResult。
    """

    def __init__(self):
        self._query = ""
        self._sub_questions: list[str] = []
        self._paper_candidates: list = []
        self._evidence_chunks: list[EvidenceChunk] = []
        self._traces: list = []
        self._dedup_logs: list = []
        self._rerank_logs: list = []

    def with_query(self, query: str) -> "RagResultBuilder":
        self._query = query
        return self

    def with_sub_questions(self, sub_questions: list[str]) -> "RagResultBuilder":
        self._sub_questions = sub_questions
        return self

    def with_paper_candidates(self, candidates) -> "RagResultBuilder":
        self._paper_candidates = candidates
        return self

    def with_evidence_chunks(
        self, chunks: list[EvidenceChunk]
    ) -> "RagResultBuilder":
        self._evidence_chunks = chunks
        return self

    def with_traces(self, traces) -> "RagResultBuilder":
        self._traces = traces
        return self

    def with_dedup_logs(self, logs) -> "RagResultBuilder":
        self._dedup_logs = logs
        return self

    def with_rerank_logs(self, logs) -> "RagResultBuilder":
        self._rerank_logs = logs
        return self

    def build(self) -> RagResult:
        """构建最终的 RagResult。"""
        # 生成 coverage_notes
        coverage_notes = self._generate_coverage_notes()

        return RagResult(
            query=self._query,
            sub_questions=self._sub_questions,
            rag_strategy="keyword+dense+rrf+evidence_typing",
            paper_candidates=self._paper_candidates,
            evidence_chunks=self._evidence_chunks,
            retrieval_trace=self._traces,
            dedup_log=self._dedup_logs,
            rerank_log=self._rerank_logs,
            coverage_notes=coverage_notes,
            total_papers=len(self._paper_candidates),
            total_chunks=len(self._evidence_chunks),
            retrieved_at=datetime.utcnow().isoformat() + "Z",
        )

    def _generate_coverage_notes(self) -> list[str]:
        """生成覆盖度注释。"""
        notes = []
        if not self._evidence_chunks:
            notes.append("WARNING: 无检索到任何 evidence chunks")
        # 检查各 support_type 覆盖
        types = set(c.support_type for c in self._evidence_chunks)
        for stype in ["method", "result"]:
            if stype not in types:
                notes.append(f"NOTE: 缺少 {stype} 类型 evidence")
        return notes
```

---

## 9. API 端点设计

### 新端点：`POST /corpus/evidence`

**请求**：
```python
class EvidenceSearchRequest(BaseModel):
    # 必须：论文范围
    paper_ids: list[str] = Field(
        ...,
        description="限定检索的论文 doc_ids 列表（来自 /corpus/search 的结果）",
    )
    canonical_ids: list[str] = Field(
        default_factory=list,
        description="可选的 canonical_id 列表",
    )

    # 检索内容
    query: str = Field(..., min_length=1, max_length=2000)
    sub_questions: list[str] = Field(default_factory=list)

    # 检索参数
    top_k_per_paper: int = Field(
        default=10, ge=1, le=50,
        description="每篇论文最多召回的 chunks 数量",
    )
    top_k_global: int = Field(
        default=50, ge=1, le=200,
        description="全局最多召回的 chunks 总数",
    )
    enable_typing: bool = Field(
        default=True,
        description="是否启用 evidence typing",
    )
```

**响应**：
```python
class EvidenceSearchResponse(BaseModel):
    rag_result: RagResultResponse
    chunks: list[EvidenceChunkResponse]
    trace: list[RetrievalTraceResponse]
    total_chunks: int = 0
    coverage_notes: list[str] = []
    duration_ms: float = 0.0


class EvidenceChunkResponse(BaseModel):
    chunk_id: str
    paper_id: str
    canonical_id: str = ""
    text: str = ""
    section: str = ""
    page_start: int = 1
    page_end: int = 1
    scores: ScoreBreakdownResponse  # keyword / dense / rrf
    support_type: str = "claim_support"
    matched_query: str = ""
    chunk_path: str = ""


class RagResultResponse(BaseModel):
    query: str
    sub_questions: list[str]
    rag_strategy: str
    total_papers: int = 0
    total_chunks: int = 0
    coverage_notes: list[str] = []
    retrieved_at: str = ""
```

---

## 10. 文件结构

```
src/corpus/search/
├── retrievers/
│   ├── ... (existing)
│   └── chunk_retriever.py    # 新增：fine chunk evidence retrieval
├── evidence_typer.py          # 新增：section-based evidence typing
├── result_builder.py          # 新增：RagResult builder
├── models.py                  # 新增：EvidenceChunk 模型

src/api/routes/
└── corpus_evidence.py         # 新增：POST /corpus/evidence 端点

src/models/
└── paper.py                   # 修改：扩展 RagResult 模型

.env.example                    # 修改（如有需要）

tests/corpus/search/
├── test_chunk_retriever.py   # 新增
├── test_evidence_typer.py    # 新增
└── test_result_builder.py    # 新增
```

---

## 11. 与现有代码的关系

- **复用** `ChunkStore`：fine chunk 存储已完整，直接使用
- **复用** `CorpusRepository`：Milvus 向量连接复用
- **复用** `PaperDeduper` / `CrossEncoderReranker`：模块 5 的 dedup/rerank 结果直接传入
- **增强** `RagResult` 模型：扩展 `src/models/paper.py`
- **独立**：不修改现有的 `/corpus/search` 端点，模块 6 独立演进

---

## 12. 交付物清单

- [ ] `src/corpus/search/retrievers/chunk_retriever.py` — ChunkRetriever
- [ ] `src/corpus/search/evidence_typer.py` — EvidenceTyper
- [ ] `src/corpus/search/result_builder.py` — RagResultBuilder
- [ ] `src/corpus/search/models.py` — EvidenceChunk 模型
- [ ] `src/models/paper.py` — 扩展 RagResult / RerankLog
- [ ] `src/api/routes/corpus_evidence.py` — POST /corpus/evidence 端点
- [ ] `src/corpus/search/__init__.py` — 新增导出
- [ ] `tests/corpus/search/test_chunk_retriever.py`
- [ ] `tests/corpus/search/test_evidence_typer.py`
- [ ] `tests/corpus/search/test_result_builder.py`

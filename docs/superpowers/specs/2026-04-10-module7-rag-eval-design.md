# 模块 7：RAG Eval — 检索系统性能评测

**日期**: 2026-04-10
**状态**: 已批准
**负责人**: PaperReader Agent

---

## 1. 核心定位

模块 7 是 Phase 2 RAG 主链的"验证闭环"：

```
模块 4 → 模块 5 → 模块 6 → [模块 7 评测] → 指导 retriever tuning → 模块 4–6 迭代
```

目标：**量化证明不同检索策略（keyword-only / dense-only / hybrid / multistage）的性能差异**。

---

## 2. 评测的四层指标体系

### Layer 1: Paper Retrieval（模块 4 评测）

评估"论文候选池"的质量。

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| **Paper Recall@K** | gold papers 中被召回的比例 | Recall = TP / (TP + FN) |
| **Paper MRR** | 首个 gold paper 的排名倒数 | MRR = 1 / rank_of_first_gold |
| **Paper NDCG@K** | 排名质量（考虑位置权重） | NDCG = DCG / IDCG |
| **PAPER_MAP@K** | 平均精度（多 gold 场景） | AP = Σ P@k × rel@k / #gold |

### Layer 2: Paper Ranking（模块 5 评测）

评估 dedup + rerank 后的排序质量。

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| **Ranking NDCG@K** | rerank 后 top-K 的排序质量 | 同上 |
| **Ranking MRR** | rerank 后首个 gold paper 排名 | 同上 |
| **Dedup Precision** | 去重后保留的真正不同论文比例 | TP_canonical / total_deduped |
| **Rerank Improvement Rate** | rerank 后 vs RRF baseline 的提升 | (NDCG_rerank - NDCG_rrf) / NDCG_rrf |

### Layer 3: Evidence Retrieval（模块 6 评测）

评估"证据块"的质量。

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| **Evidence Recall@K** | gold evidence 中被召回的比例 | Recall = TP / (TP + FN) |
| **Evidence Precision@K** | 召回 evidence 中真正相关的比例 | Precision = TP / (TP + FP) |
| **Support Span Hit Rate** | 是否命中了 gold section/span | Hit = predicted_section == gold_section |
| **Evidence Type Accuracy** | support_type 分类准确率 | Accuracy = correct_type / total |
| **Evidence Coverage Rate** | 各 support_type（method/result）的覆盖情况 | Coverage = types_present / types_required |

### Layer 4: Citation / Grounding（模块 3–6 联合评测）

评估 claim-evidence 的对应关系。

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| **Citation Reachability Rate** | citation URL 可达比例 | Reachable / Total |
| **Supported Claim Rate** | claim 被 evidence 支撑的比例 | Supported / Total |
| **Unsupported Claim Rate** | claim 无 evidence 支撑的比例 | Unsupported / Total |
| **Coverage Gap Count** | 某 sub-question 下明显缺 evidence 的数量 | Manual count |
| **Grounding Score** | 综合 grounding 质量（0–1） | (Supported - Unsupported) / Total |

---

## 3. 评测用例设计

### RagEvalCase Schema

```python
@dataclass
class RagEvalCase:
    """单条评测用例。"""
    case_id: str = ""              # 唯一标识
    query: str = ""                # 检索 query
    sub_questions: list[str] = []  # 子问题列表

    # Gold data（人工标注或复用公开数据集）
    gold_papers: list[GoldPaper] = field(default_factory=list)
    gold_evidence: list[GoldEvidence] = field(default_factory=list)
    gold_claims: list[GoldClaim] = field(default_factory=list)

    # 评测参数
    recall_top_k: int = 100
    rerank_top_m: int = 50
    evidence_top_k: int = 50

    # 元信息
    source: str = ""               # "manual" / "scifact" / "paperqa"
    notes: str = ""


@dataclass
class GoldPaper:
    """Gold paper 标准。"""
    title: str = ""
    canonical_id: str = ""          # 与 corpus 中 canonical_id 对应
    arxiv_id: str = ""
    expected_rank: int = 0         # 期望排名（1=最重要）


@dataclass
class GoldEvidence:
    """Gold evidence 标准。"""
    paper_title: str = ""
    expected_section: str = ""      # 期望命中的 section
    text_hint: str = ""            # 文本片段（用于宽松匹配）
    sub_question_id: str = ""


@dataclass
class GoldClaim:
    """Gold claim 标准。"""
    claim_text: str = ""
    supported_by_paper: str = ""
    supported_by_evidence_section: str = ""
```

### 评测集组织

```
tests/eval/cases/
├── phase2_smoke.jsonl        # 冒烟测试（5 cases，快速验证）
├── phase2_regression.jsonl    # 回归测试（20 cases，覆盖主流场景）
└── phase2_full.jsonl          # 完整评测集（50+ cases，按需运行）
```

---

## 4. 匹配策略（宽松 vs 严格）

### 宽松匹配（低成本，用于初筛）

```python
def loose_match(predicted, gold) -> bool:
    """宽松匹配：同论文 + section 关键词重叠。"""
    return (
        predicted.paper_id == gold.paper_id
        and _section_overlap(predicted.section, gold.expected_section)
    )

def _section_overlap(pred_section: str, gold_section: str) -> bool:
    """检查 section 是否语义重叠。"""
    pred_tokens = set(pred_section.lower().split())
    gold_tokens = set(gold_section.lower().split())
    overlap = pred_tokens & gold_tokens
    return len(overlap) >= min(1, len(gold_tokens) - 1)
```

### 严格匹配（高成本，用于精细评测）

```python
def strict_match(predicted, gold) -> bool:
    """严格匹配：section + text similarity。"""
    return (
        loose_match(predicted, gold)
        and _text_similarity(predicted.text, gold.text_hint) >= 0.7
    )

def _text_similarity(text1: str, text2: str) -> float:
    """基于 token overlap 的相似度。"""
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())
    return len(tokens1 & tokens2) / max(len(tokens1 | tokens2), 1)
```

---

## 5. 多策略比较框架

### 评测策略列表

```python
STRATEGIES = {
    "keyword_only": {
        "description": "仅 BM25 keyword 检索",
        "recall_top_k": 100,
        "dense_weight": 0.0,
    },
    "dense_only": {
        "description": "仅向量检索（all-MiniLM-L6-v2）",
        "recall_top_k": 100,
        "keyword_weight": 0.0,
    },
    "hybrid_basic": {
        "description": "keyword + dense RRF fusion（各 0.5）",
        "recall_top_k": 100,
        "keyword_weight": 0.5,
        "dense_weight": 0.5,
    },
    "hierarchical_multistage": {
        "description": "coarse→fine chunk + CrossEncoder rerank",
        "recall_top_k": 100,
        "rerank_enabled": True,
        "evidence_recall_enabled": True,
    },
}
```

### 策略比较报告

```python
@dataclass
class StrategyComparisonReport:
    """多策略比较报告。"""
    strategies: list[str] = field(default_factory=list)
    per_strategy_metrics: dict[str, StrategyMetrics] = field(default_factory=dict)
    best_per_metric: dict[str, str] = field(default_factory=dict)  # metric → best strategy
    winner: str = ""   # 综合最优策略


@dataclass
class StrategyMetrics:
    """单个策略的评测指标。"""
    strategy_name: str = ""
    # Layer 1
    paper_recall_10: float = 0.0
    paper_recall_50: float = 0.0
    paper_mrr: float = 0.0
    paper_ndcg_10: float = 0.0
    # Layer 2
    ranking_ndcg_10: float = 0.0
    dedup_precision: float = 0.0
    rerank_improvement: float = 0.0
    # Layer 3
    evidence_recall_10: float = 0.0
    evidence_precision_10: float = 0.0
    support_span_hit_rate: float = 0.0
    evidence_type_accuracy: float = 0.0
    # Layer 4
    citation_reachability: float = 0.0
    supported_claim_rate: float = 0.0
    unsupported_claim_rate: float = 0.0
    grounding_score: float = 0.0
    # 统计
    cases_run: int = 0
    errors: int = 0
    avg_duration_ms: float = 0.0
```

---

## 6. 单 Case 执行流程

```python
def run_single_case(
    case: RagEvalCase,
    strategy: str,
    runner: RagEvalRunner,
) -> EvalCaseResult:
    """执行单条评测用例。"""
    # Step 1: Paper Retrieval（模块 4）
    paper_results = runner.retriever.search(
        query=case.query,
        sub_questions=case.sub_questions,
        recall_top_k=case.recall_top_k,
        keyword_weight=strategy_config.get("keyword_weight", 0.5),
        dense_weight=strategy_config.get("dense_weight", 0.5),
    )

    # Step 2: Dedup + Rerank（模块 5）
    deduped = runner.deduper.dedup(paper_results)
    if strategy_config.get("rerank_enabled"):
        reranked = runner.reranker.rerank_with_fusion(
            query=case.query,
            candidates=deduped,
            fusion_weights=(0.4, 0.6),
        )
    else:
        reranked = sorted(deduped, key=lambda c: c.rrf_score, reverse=True)

    # Step 3: Evidence Retrieval（模块 6）
    if strategy_config.get("evidence_recall_enabled"):
        paper_ids = [c.primary_doc_id for c in deduped]
        evidence_chunks = runner.chunk_retriever.retrieve(
            paper_ids=paper_ids,
            query=case.query,
            sub_questions=case.sub_questions,
            top_k_global=case.evidence_top_k,
        )
    else:
        evidence_chunks = []

    # Step 4: 收集 artifacts
    artifacts = {
        "initial_candidates": paper_results,
        "deduped_papers": deduped,
        "reranked_papers": reranked,
        "evidence_chunks": evidence_chunks,
    }

    # Step 5: 计算四层指标
    metrics = runner.metrics.compute_all(
        predicted=artifacts,
        gold=case,
        strategy=strategy,
    )

    # Step 6: 构建结果
    return EvalCaseResult(
        case_id=case.case_id,
        strategy=strategy,
        artifacts=artifacts,
        metrics=metrics,
        duration_ms=...,
        errors=[],
    )
```

---

## 7. API 端点设计

### POST /evals/rag/run

**请求**：
```python
class RagEvalRunRequest(BaseModel):
    # 评测用例来源
    case_source: Literal["inline", "smoke", "regression", "full"] = "smoke"
    cases: list[RagEvalCase] = []           # case_source=inline 时使用
    case_ids: list[str] = []                # 只运行指定 case

    # 评测策略
    strategies: list[str] = ["hybrid_basic"]  # 要评测的策略列表
    comparison_mode: bool = True              # 多策略对比模式

    # 覆盖度（可选）
    run_layers: list[int] = [1, 2, 3, 4]   # 评测哪些层
    verbose: bool = False                     # 是否包含 artifact 详情

    # 过滤
    min_cases: int = 1
    max_duration_ms: float = 60000.0
```

**响应**：
```python
class RagEvalRunResponse(BaseModel):
    report: RagEvalReport
    strategy_comparison: StrategyComparisonReport | None = None
    duration_ms: float = 0.0
    cases_run: int = 0
    cases_failed: int = 0
```

### GET /evals/rag/cases

返回可用评测用例列表。

---

## 8. 文件结构

```
src/eval/rag/
├── __init__.py
├── models.py           # RagEvalCase, GoldPaper, GoldEvidence, GoldClaim
├── metrics.py         # 四层指标计算
├── matchers.py        # 宽松/严格匹配逻辑
├── runner.py          # 评测执行器
├── report.py          # RagEvalReport 生成

src/api/routes/
└── evals.py           # /evals/rag/run 端点

tests/eval/rag/
├── test_metrics.py
├── test_matchers.py
└── test_runner.py

tests/eval/cases/
├── phase2_smoke.jsonl     # 5 cases
├── phase2_regression.jsonl # 20 cases
└── README.md              # 如何标注新的 cases
```

---

## 9. 与模块 4–6 的集成关系

```
RagEvalRunner
    ├─ PaperRetriever      (模块 4)
    ├─ PaperDeduper        (模块 5)
    ├─ CrossEncoderReranker (模块 5)
    ├─ ChunkRetriever      (模块 6)
    └─ EvidenceTyper       (模块 6)
```

所有依赖通过依赖注入传入，评测代码不直接持有 store 引用。

---

## 10. 交付物清单

- [ ] `src/eval/rag/models.py` — 数据模型（RagEvalCase、GoldPaper、GoldEvidence、GoldClaim）
- [ ] `src/eval/rag/metrics.py` — 四层指标计算
- [ ] `src/eval/rag/matchers.py` — gold vs predicted 匹配逻辑
- [ ] `src/eval/rag/report.py` — 评测报告生成
- [ ] `src/eval/rag/runner.py` — 评测执行器
- [ ] `src/api/routes/evals.py` — POST /evals/rag/run 端点
- [ ] `tests/eval/rag/test_metrics.py` — 指标计算单元测试
- [ ] `tests/eval/rag/test_matchers.py` — 匹配逻辑单元测试
- [ ] `tests/eval/rag/test_runner.py` — 执行器单元测试
- [ ] `tests/eval/cases/phase2_smoke.jsonl` — 5 个冒烟测试用例

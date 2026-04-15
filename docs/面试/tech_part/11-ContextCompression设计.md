# PaperReader Agent — Context Compression 上下文压缩设计

> 本文档基于 `docs/features_oncoming/context-compression-for-report-generation.md`，分析当前问题并给出详细技术设计。

---

## 1. 现状问题分析

### 1.1 当前上下文流经报告生成管道的数据量

```
用户查询
    ↓
clarify_node          → 短文本（ResearchBrief），无需压缩
    ↓
search_plan_node      → SearchPlan（短），无需压缩
    ↓
search_node           → 返回 RagResult（含 paper_candidates，原始 hits）
    ↓
extract_node          → PaperCards（最多 30 张）  ←─┐
    ↓                                        │
draft_node  ────────────────────────────────┘
    │
    └→ 传入 _build_draft_report:
        cards[:20] × 每张完整 abstract (~1500 chars)
        + system prompt (~2000 chars)
        + brief_ctx (~500 chars)
        + output (~8000 chars)
        ─────────────────────────────────
        总计 ~26k tokens → 直接送入 LLM
        ⚠️ 无任何压缩
```

### 1.2 当前唯一的"截断"机制（不是压缩）

| 位置 | 截断策略 | 效果 |
|------|---------|------|
| `extract_node` | `MAX_EXTRACT_CANDIDATES = 30` | 限制候选数量，内容不变 |
| `draft_node` | `cards[:20]` | 丢弃第 20 张之后的卡片 |
| `AnalystAgent` | `cards[:10]` | 丢弃第 10 张之后的卡片 |

这些都是**硬截断**，不是**压缩**：
- 丢弃的卡片内容永久丢失
- 保留下来的卡片仍携带完整 abstract
- LLM 必须处理所有原始内容

### 1.3 Token 分布

```
每张 PaperCard abstract 长度分布：
- 短 abstract：~500 chars ≈ 125 tokens
- 正常 abstract：~1500 chars ≈ 375 tokens  ← 典型值
- 长 abstract：~3000+ chars ≈ 750 tokens

20 张卡片的 token 分布：
- 最佳情况（20 × 500）：~10k tokens
- 典型情况（20 × 1500）：~30k tokens  ⚠️ 超限
- 最坏情况（混合长尾）：~50k tokens  ⚠️ 严重超限
```

---

## 2. 多层压缩管道设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                  上下文压缩管道（Compression Pipeline）              │
│                                                                  │
│  Layer 0: Raw Input                                             │
│  20 × paper_cards (每张 ~1500 chars abstract) = ~30k chars     │
│                                                                  │
│         ↓ compress_paper_cards(paper_cards[:20])                 │
│                                                                  │
│  Layer 1: Structured Summary ────────────────────────────────   │
│  - extract_structured_cards()：从 abstract 提取结构化字段        │
│  - build_taxonomy()：论文分类（识别技术路线/子领域）             │
│  - build_comparison_matrix()：对比矩阵（87% 压缩率）            │
│  Output: ~4k chars + 结构化矩阵                                 │
│                                                                  │
│         ↓ build_evidence_pool(论文分组 + 矩阵)                   │
│                                                                  │
│  Layer 2: Section-level Evidence Pool ────────────────────────  │
│  - 对每个 section 预分配 token 预算                             │
│  - 中心论文（被多篇引用）分配更多 token                          │
│  - 边缘论文（孤立）截断至核心声明                               │
│  Output: 每个 section 的 evidence pool（动态大小）              │
│                                                                  │
│         ↓ write_with_evidence(section_pool)                      │
│                                                                  │
│  Layer 3: Per-Section Drafting ──────────────────────────────  │
│  - 为每个 section 独立分配 token 预算                           │
│  - 按 pool 分配比例分配 token                                   │
│  - 无需超量读取，一次 LLM 调用完成单 section 写作               │
│  Output: 各 section 草稿                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心压缩算法

### 3.1 Taxonomy — 论文分类压缩

**目的**：将 20+ 篇论文按技术路线/子领域分类，减少"平铺罗列"

```python
@dataclass
class Taxonomy:
    categories: list[TaxonomyCategory]
    cross_category_themes: list[str]   # 跨分类主题（最重要）
    timeline: list[str]                 # 技术发展时间线
    key_papers: list[str]              # 必引用的关键论文

@dataclass
class TaxonomyCategory:
    name: str                           # "Benchmark驱动" / "Agent架构" / ...
    description: str
    papers: list[str]                   # 该分类下的论文标题
    key_characteristics: list[str]       # 该分类的核心特征
    shared_insights: list[str]           # 该分类内跨论文的共同发现
    conflicts: list[str]                # 分类内论文间的冲突结论


def build_taxonomy(paper_cards: list[PaperCard], brief: ResearchBrief) -> Taxonomy:
    """
    将论文按技术路线分类：

    压缩率：~90%（从 30k chars → ~3k chars）
    """
    llm = build_reason_llm(settings, max_tokens=4096)

    prompt = f"""你是一个论文分类专家。
给定 {len(paper_cards)} 篇论文的信息，请按技术路线/子领域分类。

论文信息：
{_render_cards(paper_cards)}

请输出 JSON 格式的分类结果，包含：
1. categories：分类列表（每类包含名称、描述、论文列表、关键特征、共享发现、冲突结论）
2. cross_category_themes：跨分类主题
3. timeline：技术发展时间线
4. key_papers：必须引用的关键论文
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    return Taxonomy.model_validate_json(response.content)
```

### 3.2 Compressed Cards — 摘要压缩

**目的**：将每张卡片压缩到 ~300 chars（保留核心发现）

```python
@dataclass
class CompressedCard:
    title: str
    arxiv_id: str
    core_claim: str         # 核心发现（一句话）
    method_type: str         # 方法类型
    key_result: str          # 关键数值结果（如果有）
    role_in_taxonomy: str    # 在分类中的角色
    connections: list[str]   # 与其他论文的关系/对比


def build_compressed_abstracts(
    paper_cards: list[PaperCard],
    taxonomy: Taxonomy,
) -> list[CompressedCard]:
    """
    将论文摘要压缩为关键信息：

    压缩率：~80%（从 ~1500 chars → ~300 chars / 张）
    """
    llm = build_reason_llm(settings, max_tokens=8192)

    # 构建包含 taxonomy 上下文的压缩 prompt
    taxonomy_context = f"分类体系：{[c.name for c in taxonomy.categories]}"

    prompt = f"""给定以下论文分类体系：
{taxonomy_context}

请将每篇论文压缩为关键信息（每篇 ~300 chars）：

论文信息：
{_render_cards(paper_cards)}

输出 JSON 格式的压缩卡片列表。
"""
    response = llm.invoke([HumanMessage(content=prompt)])
    return [CompressedCard.model_validate_json(c) for c in json.loads(response.content)]
```

### 3.3 Evidence Pool — Section 级 Evidence 池

**目的**：按 section 分配 evidence，避免一篇论文被所有 section 全文引用

```python
@dataclass
class EvidencePool:
    section: str
    token_budget: int           # 该 section 的 token 预算
    papers: list[PoolEntry]    # 分配给该 section 的论文

@dataclass
class PoolEntry:
    card: CompressedCard
    allocated_chars: int        # 分配给该论文的字符数
    focus_aspect: str          # 该 section 关注该论文的哪个方面


def build_evidence_pools(
    compressed_cards: list[CompressedCard],
    taxonomy: Taxonomy,
    brief: ResearchBrief,
) -> dict[str, EvidencePool]:
    """
    为每个 section 构建 evidence pool：

    分配策略：
    1. 识别每篇论文在不同 section 的相关性（通过 taxonomy 匹配）
    2. 中心论文（被多个分类引用）→ 所有相关 section 都分配 evidence
    3. 边缘论文（仅属于一个分类）→ 只在相关 section 出现
    4. token 预算按 section 重要性 + 相关论文数量动态分配
    """
    # Section token 预算
    SECTION_BUDGETS = {
        "introduction": 15000,
        "background": 10000,
        "taxonomy": 15000,
        "methods": 20000,
        "datasets": 8000,
        "evaluation": 10000,
        "discussion": 8000,
        "future_work": 6000,
        "conclusion": 4000,
    }

    pools = {}
    for section_name in SECTION_BUDGETS:
        budget = SECTION_BUDGETS[section_name]

        # 选择与该 section 相关的论文
        relevant_cards = _select_relevant_cards(compressed_cards, section_name, taxonomy)

        # 按相关性分配 token
        entries = _allocate_tokens(relevant_cards, budget)

        pools[section_name] = EvidencePool(
            section=section_name,
            token_budget=budget,
            papers=entries,
        )

    return pools
```

---

## 4. ContextBudget 全局预算管理

### 4.1 预算分配

```python
class ContextBudget:
    """
    管理整个报告生成的 token 预算。

    DeepSeek context window: ~128k tokens
    目标使用率: 70-80%（保留 buffer 给 system prompt + output）
    可用 tokens: ~90k tokens

    分配：
    - system prompt: ~3k tokens
    - brief context: ~0.5k tokens
    - compressed_cards: ~8k tokens (20 × ~400)
    - taxonomy: ~3k tokens
    - comparison_matrix: ~5k tokens
    - per-section evidence: ~60k tokens (各 section 按需分配)
    - output buffer: ~10k tokens
    """

    TOTAL_BUDGET = 90000  # tokens
    SECTION_BUDGETS = {
        "introduction": 15000,
        "background": 10000,
        "taxonomy": 15000,
        "methods": 20000,
        "datasets": 8000,
        "evaluation": 10000,
        "discussion": 8000,
        "future_work": 6000,
        "conclusion": 4000,
    }

    def allocate(self, section: str, evidence: list[CompressedCard]) -> str:
        """将压缩后的 evidence 分配给 section，超量时截断"""
        budget = self.SECTION_BUDGETS.get(section, 5000)
        allocated = self._pack_evidence(evidence, budget)
        return allocated  # 返回压缩后的文本
```

---

## 5. 实施路径

### Phase 1：在 extract_node 后、draft_node 前插入压缩层

```
extract_node  →  extract_compression_node  →  draft_node
```

新增 `extract_compression_node`：

```python
def extract_compression_node(state: dict) -> dict:
    """在 extract 和 draft 之间插入上下文压缩"""
    paper_cards = state.get("paper_cards", [])
    brief = state.get("brief")

    # Step 1: 构建 Taxonomy
    taxonomy = build_taxonomy(paper_cards, brief)

    # Step 2: 压缩论文摘要
    compressed = build_compressed_abstracts(paper_cards, taxonomy)

    # Step 3: 构建 Per-Section Evidence Pool
    pools = build_evidence_pools(compressed, taxonomy, brief)

    return {
        "taxonomy": taxonomy,
        "compressed_cards": compressed,
        "evidence_pools": pools,
    }
```

### Phase 2：修改 draft_node 使用压缩后的上下文

将 `_build_draft_report` 从"传入原始 20 张卡片"改为"传入 evidence_pools + compressed_cards"：

```python
def draft_node(state: dict) -> dict:
    taxonomy = state.get("taxonomy")
    compressed_cards = state.get("compressed_cards", [])
    evidence_pools = state.get("evidence_pools", {})

    # 为每个 section 独立生成
    sections = {}
    for section_name, pool in evidence_pools.items():
        section_text = _write_section(
            section_name,
            pool=pool,
            taxonomy=taxonomy,
            brief=state["brief"],
        )
        sections[section_name] = section_text

    # Claims 从 taxonomy + compressed_cards 生成
    claims = _generate_claims_from_taxonomy(taxonomy, compressed_cards)
```

---

## 6. 预期效果

| 指标 | 当前 | 压缩后 |
|------|------|--------|
| Context tokens | ~26k | ~15k |
| Section 引用多样性 | 低（LLM 选前几张） | 高（按相关性分配） |
| Introduction 引用数 | 3-5 篇 | 10+ 篇 |
| 摘要复读问题 | 严重 | 基本消除 |
| Introduction 字数 | 800-1200 chars | 2500-3500 chars |

# PaperReader Agent — Grounding 与引用验证体系

---

## 1. 三段式 Grounding Pipeline

### 1.1 整体流程

```
┌──────────────────────────────────────────────────────────────────┐
│                  ground_draft_report() — 三段式验证                │
│                                                                   │
│  DraftReport (draft_node 产出)                                    │
│         │                                                        │
│         ▼                                                        │
│  ┌─────────────────┐                                             │
│  │ resolve_citations │ ← URL 可达性检查 + source tier 分类        │
│  └────────┬────────┘                                             │
│           │ 返回 ResolvedReport                                    │
│           ▼                                                        │
│  ┌─────────────────┐                                             │
│  │  verify_claims  │ ← LLM Judge: claim vs evidence 配对          │
│  └────────┬────────┘                                             │
│           │ 返回 VerifiedReport                                    │
│           ▼                                                        │
│  ┌─────────────────┐                                             │
│  │  format_output  │ ← 应用 abstention policy + Markdown 渲染      │
│  └────────┬────────┘                                             │
│           │                                                        │
│           ▼                                                        │
│  FinalReport (带 grounding_stats)                                  │
└──────────────────────────────────────────────────────────────────┘
```

**文件**：`src/research/services/grounding.py`

```python
def ground_draft_report(draft_report: DraftReport) -> FinalReport:
    """
    三段式 Grounding Pipeline：

    1. resolve_citations：
       - URL 可达性检查（httpx HEAD request）
       - Source Tier 分类（A/B/C/D 四级权威度）
       - 填充 fetched_content

    2. verify_claims：
       - LLM Judge 对每个 claim vs citation 配对打分
       - 判断支持/部分支持/不支持

    3. format_output：
       - 应用 abstention policy（不可靠 claim 标记 abstained）
       - 生成最终 Markdown 渲染
    """
    # Step 1: Citation Resolution
    resolved = resolve_citations(draft_report.citations)

    # Step 2: Claim Verification
    verified = verify_claims(draft_report.claims, resolved)

    # Step 3: Format Output
    final = format_output(verified, resolved)

    return final
```

---

## 2. Step 1: Citation Resolution

**文件**：`src/graph/nodes/resolve_citations.py`

```python
def resolve_citations(citations: list[Citation]) -> DraftReport:
    """对每个 Citation 做 URL 可达性检查 + Source Tier 分类"""

    results = []
    for citation in citations:
        # URL 可达性检查
        reachable = _check_url_reachable(citation.url)

        # Source Tier 分类
        source_tier = classify_source_tier(citation.url, citation.label)

        # 如果可 reach，尝试获取 fetched_content
        fetched = None
        if reachable:
            fetched = _fetch_citation_content(citation.url)

        results.append(citation.model_copy(update={
            "reachable": reachable,
            "source_tier": source_tier,
            "fetched_content": fetched,
        }))

    return draft_report.model_copy(update={"citations": results})
```

### 2.1 Source Tier 四级分类

**文件**：`src/verification/source_tiers.py`

```python
class SourceTier(Enum):
    """
    论文权威度四级分类：

    - Tier A：顶会/顶刊（ACL, NeurIPS, ICML, Nature, Science, JAMA...）
    - Tier B：知名会议/期刊（EMNLP, ICLR, AAAI, IEEE...）
    - Tier C：预印本/技术报告（arXiv）
    - Tier D：博客/论坛/非正式来源
    """
    A = "tier_a"   # 顶级权威
    B = "tier_b"   # 知名来源
    C = "tier_c"   # 预印本/技术报告
    D = "tier_d"   # 非正式来源


def classify_source_tier(url: str, label: str) -> SourceTier:
    """基于 URL 模式分类权威度"""
    if any(domain in url for domain in ["arxiv.org", "export.arxiv.org"]):
        return SourceTier.C
    if any(domain in url for domain in ["nature.com", "science.org", "nejm.org"]):
        return SourceTier.A
    if any(domain in url for domain in ["aclanthology.org", "proceedings.neurips",
                                          "openreview.net", "arxiv.org"]):
        return SourceTier.B
    return SourceTier.D
```

### 2.2 URL 可达性检查

```python
def _check_url_reachable(url: str, timeout: float = 10.0) -> bool:
    """HEAD request 检查 URL 可达性"""
    try:
        response = httpx.head(url, timeout=timeout, follow_redirects=True)
        return response.status_code < 400
    except Exception:
        return False


def _fetch_citation_content(url: str, max_chars: int = 2000) -> str | None:
    """获取引用内容片段（用于 claim verification）"""
    try:
        response = httpx.get(url, timeout=15.0)
        # 清理 HTML 标签
        text = extract_text_from_html(response.text)
        return text[:max_chars]
    except Exception:
        return None
```

---

## 3. Step 2: Claim Verification

**文件**：`src/graph/nodes/verify_claims.py`

### 3.1 LLM Judge 机制

```python
def verify_claims(claims: list[Claim], resolved_report: DraftReport) -> DraftReport:
    """
    对每个 claim 做 evidence grounding 验证：

    策略：
    - 提取 claim 引用的所有 citations
    - 对每个 (claim, citation) 配对调用 LLM Judge
    - 综合多 citation 判断 overall_status
    """

    for claim in claims:
        citation_labels = claim.citation_labels

        # 找到对应的 citations
        cited_citations = [
            c for c in resolved_report.citations
            if c.label in citation_labels
        ]

        # 构建 verification prompt
        verification_results = []
        for citation in cited_citations:
            if not citation.fetched_content:
                verification_results.append(ClaimSupport(
                    citation_label=citation.label,
                    support_level="unreachable",
                    reasoning="引用内容无法获取",
                ))
                continue

            # LLM Judge
            result = _llm_judge_claim_evidence(claim.text, citation.fetched_content)
            verification_results.append(result)

        # 综合判断 overall_status
        claim.supports = verification_results
        claim.overall_status = _aggregate_support_level(verification_results)
```

### 3.2 LLM Judge Prompt

```python
SYSTEM_PROMPT = """你是一个学术论文引用验证专家。
给定一个 claim（论文中的声明）和一段 evidence（引用的论文内容），
判断该 evidence 是否支持该 claim。

判断标准：
- SUPPORTED：evidence 明确支持 claim 的核心论点
- PARTIAL：evidence 部分支持 claim，或只在特定条件下成立
- UNSUPPORTED：evidence 不支持或与 claim 矛盾
- UNREACHABLE：无法获取 evidence 内容

请返回 JSON 格式：{"support_level": "SUPPORTED|PARTIAL|UNSUPPORTED|UNREACHABLE", "reasoning": "判断理由"}"""
```

### 3.3 Support Level 聚合

```python
def _aggregate_support_level(results: list[ClaimSupport]) -> str:
    """综合多 citation 的验证结果"""
    supported = sum(1 for r in results if r.support_level == "SUPPORTED")
    partial = sum(1 for r in results if r.support_level == "PARTIAL")
    unsupported = sum(1 for r in results if r.support_level == "UNSUPPORTED")

    if unsupported > 0:
        return "unsupported"
    if supported > 0 and partial == 0:
        return "supported"
    return "partial"
```

---

## 4. Step 3: Format Output + Abstention Policy

**文件**：`src/graph/nodes/format_output.py`

```python
def format_output(verified_report: DraftReport, resolved_report: DraftReport) -> FinalReport:
    """
    应用 abstention policy：

    abstention policy 规则：
    - unsupported claims：标记 abstained，不输出正文
    - partial claims：在正文中标注"[部分支持]"
    - tier D citations：降权处理
    """

    # 过滤 abstained claims
    actionable_claims = [c for c in verified_report.claims
                       if c.overall_status != "abstained"]

    # 渲染 Markdown
    markdown = _render_markdown(verified_report, resolved_report)

    # 统计 grounding stats
    stats = compute_grounding_stats(verified_report.claims, resolved_report.citations)

    return FinalReport(
        sections=verified_report.sections,
        claims=actionable_claims,
        citations=resolved_report.citations,
        grounding_stats=stats,
        markdown=markdown,
    )
```

### 4.1 GroundingStats

```python
class GroundingStats(BaseModel):
    total_claims: int
    grounded: int          # supported
    partial: int           # partial
    ungrounded: int       # unsupported
    abstained: int         # abstained（不可靠，不输出）
    tier_a_ratio: float   # Tier A 引用占比
    tier_b_ratio: float   # Tier B 引用占比
```

---

## 5. ReviewerService — 四类质量检查

**文件**：`src/research/services/reviewer.py`

```python
class ReviewerService:
    """
    四类质量检查：

    1. Paper Cards 质量检查（卡片信息完整度）
    2. 覆盖性检查（sub_questions 是否被覆盖）
    3. Claim 支撑检查（claims 是否有 evidence 支持）
    4. Citation 可达性 + 结构重复检查
    """

    def review(
        self,
        paper_cards: list[PaperCard],
        draft_report: DraftReport,
        brief: ResearchBrief,
    ) -> ReviewFeedback:
        issues = []

        # 检查 1: Paper Cards 质量
        issues.extend(self._check_paper_cards(paper_cards))

        # 检查 2: 覆盖性
        issues.extend(self._check_coverage(paper_cards, draft_report, brief))

        # 检查 3: Claim 支撑
        issues.extend(self._check_claim_support(draft_report))

        # 检查 4: Citation 可达性 + 重复
        issues.extend(self._check_citation_reachability(draft_report))
        issues.extend(self._check_duplication_consistency(draft_report))

        return ReviewFeedback(
            task_id=brief.topic,  # 简化
            passed=len([i for i in issues if i.severity == "blocker"]) == 0,
            issues=issues,
        )
```

---

## 6. 技术优势总结

| 优势 | 实现方式 |
|------|---------|
| **claim-level 验证** | 比 document-level 更精细，每个声明独立验证 |
| **Source Tier 量化** | A/B/C/D 四级分类，可统计引用权威度 |
| **abstention policy** | 不可靠 claim 不输出，避免幻觉扩散 |
| **LLM Judge 可复用** | 验证逻辑与工作流解耦，可独立测试 |
| **GroundingStats 量化** | 报告质量可量化（grounded ratio / tier ratio） |

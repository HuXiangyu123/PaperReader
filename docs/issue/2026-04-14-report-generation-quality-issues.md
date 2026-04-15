# Issue Report: 报告生成质量系统性缺陷

**日期**: 2026-04-14
**优先级**: P0 (阻塞性)
**涉及模块**: `src/research/graph/nodes/draft.py`, `src/research/agents/analyst_agent.py`, `src/research/agents/supervisor.py`, `src/skills/`
**状态**: 已确认根因

---

## 用户反馈摘要

针对查询"AI Agent 在 Coding Agent 领域目前的发展"，系统生成的报告存在三类质量问题：

1. **摘要复读**: 报告只是对若干检索到的论文摘要进行复读，整体文字毫无逻辑
2. **Introduction 浅薄**: 虽然能检索到 30+ 篇论文，但正文分析很浅，Introduction 毫无章法且只引用几篇
3. **Skills 无效**: Web 调研和 Skills 嵌入报告的效果不如直接给大模型 System Prompt 直接输出

---

## 问题一: 报告只是论文摘要复读

### 表现

生成的报告每个 section 都是"Paper A 做了什么 + Paper B 做了什么 + Paper C 做了什么"的并列结构，缺乏分析性文字，没有将多篇论文串联起来的逻辑推演。

### 根因分析

#### 根因 1: Draft Node 的单次 LLM 调用无法承担"综合分析"任务

**代码位置**: `src/research/graph/nodes/draft.py` 第 52-153 行

```52:61:src/research/graph/nodes/draft.py
def _build_draft_report(cards: list[Any], brief: Any | None) -> DraftReport:
    """用 LLM 综合 PaperCards 生成结构化 DraftReport。"""
    # 传给 LLM 最多 20 张卡片（每张 ~1500 chars abstract ≈ ~750 tokens，20 张 ≈ 15k tokens）
    # 加上 system prompt (~2k tokens) + brief ctx (~500 tokens) + output (~8k tokens) = ~26k tokens
    cards_text = _render_cards(cards[:20])
```

`draft_node` 在**一次 LLM 调用**中完成了所有工作：
- 阅读 20 张卡片 (~15k tokens)
- 理解主题
- 分类 20+ 论文
- 生成 10 个结构化 sections
- 选择引用的论文
- 生成 claims

这是 LLM 无法完成的任务。任何 LLM 在单次调用中面对 15k tokens 的输入 + 要求生成 10 个 sections + 完整 JSON 输出时，都会选择最省力的策略——将输入的摘要进行改写重组，而非真正分析。

#### 根因 2: System Prompt 明确指示"从摘要推断"而非"分析"

**代码位置**: `src/research/graph/nodes/draft.py` 第 63-113 行

```
1. EVERY section must contain substantive, specific content derived from the paper cards.
2. For the 'methods' section: For EACH paper, infer the method from its abstract and describe
3. Infer datasets from abstract when datasets field is absent in cards
4. Infer methods from abstract when methods field is absent in cards
5. Infer limitations from abstract when limitations field is absent in cards
```

System Prompt 中出现 4 次 "infer from abstract"，这直接告诉 LLM：
- 不要期望有更深入的信息
- 只需对 abstract 进行改写
- 越接近原文的改写越符合指令

正确的做法应该是**阶段化生成**：
- 先用论文内容构建中间工件（分类矩阵、对比矩阵）
- 再基于这些工件做分析性写作

#### 根因 3: Claims 是从 draft 内容中提取的，而非从 evidence 构建

**代码位置**: `src/research/graph/nodes/draft.py` 第 105-108 行

```105:108:src/research/graph/nodes/draft.py
'  "claims": [\n'
'    {"id": "c1", "text": "specific verifiable claim", "citation_labels": ["[1]", "[2]"]},\n'
'    ...\n'
"  ],\n"
```

DraftReport 中的 claims 是 LLM 在生成 report 时"顺手"写的，不是从 paper evidence 中验证后产生的。这意味着：
- Claims 的内容与 report body 高度重叠（都是对 abstract 的改写）
- 没有任何 claims 是真正经过 evidence 验证的
- Review 阶段无法通过 claims 驱动报告改进

#### 根因 4: Fallback 机制本身就是摘要复读

**代码位置**: `src/research/graph/nodes/draft.py` 第 216-454 行

当 LLM 调用失败或 JSON 解析失败时，`_fallback_draft` 会从 20 张卡片中：
- 从每张卡片的 abstract 提取前 400 字符放入 background
- 按标题关键词（"swe", "agent", "benchmark"）做粗糙分类
- 对 methods/datasets/limitations 做规则提取
- 生成模板化 conclusion

这是**最原始的摘要罗列**，完全没有任何分析性。

#### 根因 5: `_render_cards` 将完整 abstract 作为唯一可信输入

**代码位置**: `src/research/graph/nodes/draft.py` 第 550-591 行

```571:590:src/research/graph/nodes/draft.py
part = f"=== 论文 {i+1} ===\n"
part += f"标题：{title}\n"
part += f"作者：{authors_str or '未知'}\n"
# 传给 LLM 的摘要不要截断，让 LLM 自己决定消费方式
part += f"摘要（完整）：\n{full_abstract}\n"
```

LLM 收到的唯一材料是论文的完整 abstract。没有：
- 论文的方法细节（methods 可能为空）
- 实验结果的具体数值
- 各方法之间的对比信息
- 作者的分析性评述

LLM 只能从 abstract 改写，而 abstract 本身就是论文最简化的描述。

---

## 问题二: Introduction 浅薄且只引用几篇

### 表现

- Introduction 字数被限制在 800-1200 字符（System Prompt 要求）
- 即使有 30+ 篇论文，Introduction 也只引用其中的 3-5 篇
- 没有"领域发展脉络"、"研究动机"、"本综述贡献"等结构性内容
- Introduction 的写法与 body sections 没有区别

### 根因分析

#### 根因 1: Introduction 与其他 sections 接受相同的字数约束

**代码位置**: `src/research/graph/nodes/draft.py` 第 80-81 行

```
"introduction": "Comprehensive introduction (800-1200 chars) — research context, evolution of the field, '
'motivation for this survey, main contributions, paper organization roadmap"
```

800-1200 字符的 introduction **不可能**写出：
- 领域发展脉络（需要描述多条技术路线的演进）
- 研究动机（需要解释为什么这个问题重要）
- 主要贡献（需要总结综述的新视角）
- 文章结构 roadmap

真正的综述 introduction 至少需要 2000-3000 字符来覆盖这些内容。当前约束导致 LLM 只能在极小的空间内"点到为止"。

#### 根因 2: Citation 选择权完全在 LLM 单次调用中

在 `draft_node` 的单次调用中，LLM 需要同时：
- 理解 20 篇论文的内容
- 生成 10 个结构化 sections
- 选择哪些论文应该被引用

这意味着 LLM 只能选择它在前 15k tokens 中**印象最深刻**的几篇（通常是前几张卡片或标题最醒目的）。**没有机制**保证：
- Introduction 引用的论文覆盖了关键工作
- 各 section 引用的论文不重复
- 引用数量与论文重要性成正比

#### 根因 3: Review 阶段无法驱动 Citation 补充

**代码位置**: `src/research/services/reviewer.py` 第 66-146 行

ReviewerService 执行 4 类检查：
1. Paper cards 质量检查
2. 覆盖性检查
3. Claim 支撑检查
4. Citation 可达性检查

**没有任何一项检查是"Introduction 是否引用了足够多的关键论文"**。Review 的核心问题是：
- Coverage 检查只验证 sub_questions 是否被 paper_cards 覆盖，不验证论文是否被报告正文引用
- Citation reachability 检查的是 URL 是否可达，不检查 citation 是否在正文中被正确使用
- 没有生成 revision_action 来驱动"在 Introduction 中补充更多引用"

#### 根因 4: 图的路由没有"revise introduction"的回退

**代码位置**: `src/research/graph/builder.py` 第 60-64 行

```60:64:src/research/graph/builder.py
def _route_after_review(state: dict) -> str:
    """review 通过 → persist；失败 → 结束（可扩展 revise 节点）"""
    if state.get("review_passed"):
        return "persist_artifacts"
    return END
```

当 review 失败时，工作流直接 END。即使 review 识别出"Introduction 引用不足"的问题，也没有机制让 draft_node 重新生成包含更多引用的 Introduction。

---

## 问题三: Skills 没有真正嵌入报告生成流程

### 表现

虽然系统有 5 个科研相关的 Skills（`lit_review_scanner`, `claim_verification`, `comparison_matrix_builder`, `experiment_replicator`, `writing_scaffold_generator`），但实际生成的报告质量并没有因此提升，效果甚至不如直接给大模型 System Prompt 直接输出。

### 根因分析

#### 根因 1: Supervisor 默认使用 Legacy Backend，AnalystAgent 几乎不被执行

**代码位置**: `src/research/agents/supervisor.py` 第 113-126 行

```113:126:src/research/agents/supervisor.py
def _get_backend_mode(self, node_name: str) -> NodeBackendMode:
    canonical = self.normalize_node_name(node_name)
    node_mode = self.config.node_backends.mode_for(canonical)
    if node_mode != NodeBackendMode.AUTO:
        return node_mode

    execution_mode = self.config.execution_mode
    if execution_mode == ExecutionMode.LEGACY:
        return NodeBackendMode.LEGACY
    if execution_mode == ExecutionMode.V2 and self._has_v2_backend(canonical):
        return NodeBackendMode.V2
    if execution_mode == ExecutionMode.V2:
        return NodeBackendMode.LEGACY
    return NodeBackendMode.AUTO if self._has_v2_backend(canonical) else NodeBackendMode.LEGACY
```

当 `execution_mode` 为默认值（通常是 LEGACY 或未配置）时，draft 节点走 Legacy 路径，直接调用 `draft_node` 函数，**完全绕过 AnalystAgent 的 RVA（Reasoning-via-Artifacts）流水线**。

即使配置为 V2 模式，AnalystAgent 也存在严重问题（见根因 3）。

#### 根因 2: Skills 的注册与调用分离，Orchestrator 未接入工作流

**代码位置**: `src/skills/orchestrator.py` 和 `src/research/agents/supervisor.py`

Skills 系统的完整架构已经就绪：
- `src/skills/registry.py`: Skill 注册中心
- `src/skills/runner.py`: Skill 执行引擎
- `src/skills/orchestrator.py`: Agent 驱动的 Skill 编排器
- `src/skills/research_skills.py`: 5 个科研技能函数实现

但 `supervisor.collaborate()` 协调 7 个节点时，**从未调用 SkillOrchestrator**。Skills 的编排逻辑（`SkillOrchestrator.orchestrate()`）虽然存在，但在工作流中找不到任何调用点。

正确的嵌入方式应该是：
```
draft 节点之前：调用 comparison_matrix_builder skill → 构建对比矩阵
draft 节点之前：调用 writing_scaffold_generator skill → 生成报告大纲
draft 节点：基于对比矩阵和大纲生成报告
review 节点：调用 claim_verification skill → 验证 claims
```

当前的嵌入方式：**没有**。

#### 根因 3: AnalystAgent 自身的 RVA 流水线存在严重缺陷

即使 AnalystAgent 被执行，它生成的报告质量也很差：

**缺陷 A: 只处理前 10 张卡片**

```174:177:src/research/agents/analyst_agent.py
result = comparison_matrix_builder(
    {"paper_cards": cards[:10], ...}
)
```

对比矩阵只基于 10 张卡片构建，丢失了 10+ 篇论文的信息。

**缺陷 B: Outline 基于空 matrix 生成**

```247:256:src/research/agents/analyst_agent.py
result = writing_scaffold_generator(
    {
        "topic": topic,
        "paper_cards": cards[:10],
        "comparison_matrix": matrix,  # 可能是空 dict 或只有 10 行
        "desired_length": "medium",
    },
```

当 comparison_matrix_builder 失败时（常见），传入 `writing_scaffold_generator` 的是空 `matrix`，导致大纲生成退化为基础模板。

**缺陷 C: 4 个 LangGraph 节点是线性链，没有置信度反馈循环**

```422:427:src/research/agents/analyst_agent.py
workflow.add_edge(START, "seed_reasoning_state")
workflow.add_edge("seed_reasoning_state", "build_structured_cards")
workflow.add_edge("build_structured_cards", "build_comparison_matrix")
workflow.add_edge("build_comparison_matrix", "build_outline")
workflow.add_edge("build_outline", "build_report_draft")
workflow.add_edge("build_report_draft", "verify_and_finalize")
```

RVA 设计文档（第 1-23 行）明确说明：
- 工件置信度不足时应继续构建低层 artifact
- 应该有 DAG 驱动的迭代而非线性链

但实际代码是硬编码的 5 步顺序，没有任何置信度驱动的回退或迭代。

**缺陷 D: `_build_report_draft` 生成的 L4 artifact 没有写回 draft_report**

```266:327:src/research/agents/analyst_agent.py
def _build_report_draft(self, state: ReasoningState) -> dict:
    ...
    return {"draft": draft or {}, "confidence": confidence}
```

`analyst_agent.run()` 返回结果时（第 138-154 行），虽然返回了 `draft_report` 和 `draft_markdown`，但这些是经过 `_coerce_draft_report` 和 `_build_markdown` 处理后的内容。

关键问题：**comparison_matrix 和 outline 作为中间 artifact 产生了，但它们的内容从未被用于改进 report_draft 的生成**。

`AnalystAgent` 的 `_build_report_draft` 调用 LLM 时只传入了 `outline_text` 和 `matrix_text`，但：
- `outline_text` 可能只有标题和简单描述，没有详细写作指引
- `matrix_text` 是格式化的 rows 列表（每行只含 paper title + methods）
- 没有传入原始的 paper_cards abstract，LLM 只能基于 matrix 中的二手信息生成报告

#### 根因 4: Skills 的 max_tokens 限制过低

**代码位置**: `src/research/agents/analyst_agent.py` 第 281 行

```281:src/research/agents/analyst_agent.py
llm = build_reason_llm(settings, max_tokens=16384)
```

在 `_build_report_draft` 中，`max_tokens=16384` 对于生成包含 10+ sections 的完整报告可能不足（每个 section 平均 500 字符 = 5k tokens，JSON overhead = 3k tokens，总需求约 8k tokens，在 16k 上限内勉强可以，但 context 不够丰富时 LLM 会倾向于生成简略内容）。

---

## 问题间相互关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                    报告质量问题的因果链                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Skills 未接入工作流 ───────────────────────────────────┐          │
│  ↓                                                     ↓          │
│  没有 comparison_matrix ──→ 无结构化对比信息 ──→ 只能依赖 abstract    │
│  没有 writing_scaffold ──→ 无详细写作指引 ──→ 11 个 sections 无章法   │
│                                                                     │
│  Supervisor 默认 Legacy ───────────────────────────────────┐        │
│  ↓                                                     ↓        │
│  AnalystAgent 从不被调用 ──→ RVA 流水线完全未激活 ──→ skills 无从执行 │
│                                                                     │
│  单次 LLM 调用生成完整报告 ───────────────────────────┐            │
│  ↓                                               ↓            │
│  20 张卡片 + 10 sections + JSON 输出 ──→ LLM 选择最省力策略：摘要改写 │
│                                                                     │
│  Introduction 字数约束 800-1200 ─────────────────┐                  │
│  ↓                                            ↓                  │
│  无法写出领域发展脉络 + 动机 + 贡献 + roadmap ──→ 只有干巴巴的背景描述   │
│                                                                     │
│  Citation 选择在单次调用中完成 ─────────────────┐                    │
│  ↓                                         ↓                    │
│  LLM 只能选前几张卡片 ──→ Introduction 只引用 3-5 篇 ──→ 引用覆盖率低 │
│                                                                     │
│  Review 无法驱动重写 ─────────────────────────┐                    │
│  ↓                                         ↓                    │
│  review 失败 → 直接 END ──→ 即使发现问题也无法修复                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 验证方法

### Mock 测试建议

执行以下测试查询：
```
ai agent在 coding agent领域目前的发展
```

预期发现：
1. `draft_node` 生成的 report 各 section 是论文摘要的并列改写，没有逻辑串联
2. Introduction section 字符数 < 1200，引用的论文 < 5 篇
3. Supervisor 日志显示 `backend_mode=legacy`，AnalystAgent 未被调用
4. 即使 AnalystAgent 被调用，对比矩阵行数 = 0 或 < 10
5. Skills 相关代码从未在执行路径中被触发

### 关键日志检查点

```
[draft_node] drafted N sections from M papers  # N 应 > 5, M 应 = 20
[AnalystAgent] Starting Reason-via-Artifacts pipeline via LangGraph  # V2 模式才出现
[AgentSupervisor] legacy backend for draft  # 默认出现
[ground_draft_report] START  # 后续 grounding 阶段
```

---

## 建议的修复方向

### 优先级 P0（立即修复）

1. **拆分 draft_node 为多阶段节点**：不要在一次调用中完成所有工作
   - `build_taxonomy`: 先对 20 张卡片做分类，输出结构化分组
   - `build_comparison_matrix`: 对分类后的论文构建对比矩阵
   - `build_outline`: 基于分类和矩阵生成报告大纲（含 Introduction 详细写作指引）
   - `write_sections`: 分 section 顺序生成，而非一次性生成全部

2. **释放 Introduction 字数约束**：将 Introduction 字数要求提升至 2000-3000 字符

3. **强制在 V2 模式下执行 AnalystAgent**：或直接将 Skills 调用集成到 Legacy 路径中

### 优先级 P1（下一迭代）

4. **让 Review 驱动回退**：Review 失败时回到 draft 节点重写特定 section
5. **引入置信度反馈循环**：当 artifact 置信度 < 阈值时，触发回退重建
6. **让 ReviewerService 检查 citation 覆盖率**：确保每个 section 引用的论文不重复且覆盖充分

### 优先级 P2（后续优化）

7. **将 SkillOrchestrator 接入 supervisor 编排**：在关键节点自动触发 skill 执行
8. **改进 Claim 生成机制**：从 paper evidence 而非 draft content 中提取 claims
9. **为每个 section 设计独立的写作 prompt**：Introduction/Methods/Discussion 需要不同的写作策略

# 研究报告生成质量问题

> 生成时间：2026-04-11
> 状态：**已修复（2026-04-12）**
> 优先级：P0

---

## 修复记录

| Bug | 根因 | 修复 | 文件 |
|------|------|------|------|
| Q1+Q4（永远走 heuristic fast path） | `confidence >= 0.6` 阈值太低，`to_limited_brief` 的 0.68 轻易通过 | 升高阈值至 0.75，额外要求：`len(topic)>=15` 且含英文词 | `search_plan.py::_should_use_heuristic_plan` |
| Q2（搜索完全不相关） | `_is_noisy_query` 未过滤无年份的简单关键词；heuristic 查询无年份后缀 | 改进 `_is_noisy_query` + `_build_english_queries_from_topic` 强制附加年份（2024/2025） | `search_plan_policy.py` |
| Q3（报告内容不总结） | 无 paper_cards 时 `review_node` 静默继续，产生空报告 | 添加防御性检查，无 paper_cards 时提前返回带具体建议的失败 feedback | `review.py` |



---

## 一、问题概述

当前研究报告生成存在四个相互关联的严重问题：

| # | 问题 | 症状 | 优先级 |
|---|------|------|--------|
| Q1 | GPT 模型未开启思考（Thinking） | 模型直接输出短答案，无法做深度分析 | P0 |
| Q2 | 论文搜索完全不相关 | 搜索 25年SWE Agent 论文，返回 Voice Privacy/Asteroid 等无关论文 | P0 |
| Q3 | 报告内容不总结 | methods/datasets/background 全是空占位符，无实质内容 | P0 |
| Q4 | 永远走 heuristic fast path | 无论 brief 复杂度，始终触发 "Using heuristic fast path for a clear brief" | P1 |

---

## 二、问题 Q1：GPT 模型未开启思考

### 症状

```
Using heuristic fast path for a clear brief.
```

该日志来自 `SearchPlanAgent`，出现在几乎所有任务的开始阶段，无论 brief 的实际复杂度。

### 可能原因

1. **LLM 配置中未设置 `thinking` / `max_thinking_tokens`**：当前 LLM client 没有传递 thinking 相关参数
2. **所有节点都用了错误的快速模型**：REASON_MODEL 和 QUICK_MODEL 都用了低推理能力的模型
3. **Policy 层判断错误**：`_should_use_fast_path()` 的置信度阈值设置过低（0.6）

### 需要检查的文件

```
src/agent/llm.py           — LLM client 初始化，是否传递 thinking 参数
src/agent/settings.py      — REASON_MODEL / QUICK_MODEL 模型名是否支持 thinking
src/research/policies/clarify_policy.py  — _should_use_fast_path() 逻辑
src/research/agents/search_plan_agent.py  — 日志打印位置
```

---

## 三、问题 Q2：论文搜索完全不相关

### 症状

**用户 query**：`「25年ai agent在软件工程swe agent的知名论文、benchmark、架构设计，未来发展」`

**实际召回的论文**（20篇）：

| arXiv ID | 标题 | 领域 |
|----------|------|------|
| 2410.02371 | Voice Privacy Challenge 2024 | 语音隐私 |
| 2403.00634 | Asteroid 2024 BX1 Atmospheric Entry | 小行星 |
| 2409.08956 | Gravitational Wave Discovery Opportunities | 引力波 |
| 2406.10598 | Odyssey 2024 Speech Emotion Recognition | 语音情感 |
| 2407.12038 | ICAGC 2024 Audio Generation | 音频生成 |
| 2409.15402 | 2024 U.S. Election Cross-Platform IO | 选举舆论 |
| ... | 2023 年生物医学/文档处理论文 | 医疗/文档 |

**问题分析**：

1. 搜索**覆盖了正确的年份**（2023-2024），但**主题完全不匹配**
2. 用户明确要「SWE Agent / 软件工程 Agent」，实际召回的是语音、天文、医疗等论文
3. 20 篇论文中，**没有任何一篇与 SE/Agent 相关**

### 可能原因

#### 原因 A：SearchPlanAgent 的查询构造错误

`SearchPlanAgent` 生成的查询可能过于宽泛或完全错误，没有正确包含 `software engineering`、`SWE`、`agent` 等关键词。

#### 原因 B：搜索召回路径完全失效

当前 retrieval 有多个路径：

```
SearchPlanAgent 内部搜索（arXiv API）
  → 可能调用了错误的 query 或完全没搜到
  → fallback 到空的 BM25 索引
  → 返回了完全无关的论文（来自旧索引？）
```

#### 原因 C：PG BM25 索引中的论文来源可疑

PG 的 `coarse_chunks` 表有 224 条记录（旧论文），且这些旧论文的来源不确定。
如果 BM25 keyword search 依赖这些旧 chunks 而非实时 arXiv 搜索，
可能会返回完全不相关的结果。

#### 原因 D：CorpusRepository.search_papers_ex() 的 keyword_top_k 设置过大

```python
keyword_top_k=100  # 如果 BM25 索引中有大量无关论文，会召回 100 条垃圾
```

### 需要检查的文件

```
src/research/agents/search_plan_agent.py     — 搜索 query 是如何生成的
src/corpus/search/retrievers/paper_retriever.py  — keyword search 实现
src/corpus/store/repository.py                 — search_papers_ex() keyword_top_k 参数
src/corpus/search/retrievers/keyword_retriever.py  — BM25 实现
scripts/ingest_papers.py                       — 旧 chunks 来源，是否污染了 BM25
```

### 调试步骤

1. 在 `SearchPlanAgent` 中打印生成的 search queries
2. 单独调用 arXiv API，验证 query 能否搜到相关论文
3. 检查 PG `coarse_chunks` 中的论文 topic 分布
4. trace 搜索结果从 arXiv → PG → 合并的完整链路

---

## 四、问题 Q3：报告内容不总结

### 症状

生成的报告结构完整（introduction/methods/datasets/background/future_work/conclusion），但**内容完全无实质信息**：

```
introduction
本综述围绕「25年ai agent在软件工程swe agent...」，共分析了 20 篇相关论文。

methods
（方法对比待补充，可参考各论文摘要）

datasets
（数据集信息待补充）

background
相关研究背景概述如下：
In this work, we describe our submissions for the Voice Privacy Challenge 2024.
[Asteroid 2024 BX1...]  ← 完全不相关的论文摘要直接拼接
```

**核心问题**：

1. `methods`、`datasets` 完全没有实质性内容，是占位符文本
2. `background` 直接拼接了完全不相关论文的摘要（这些论文本就不该被召回）
3. `taxonomy`、`evaluation`、`discussion` 全是空占位符
4. 报告引用了 20 篇论文，但这些论文与 topic 完全不符

### 可能原因

#### 原因 A：「草稿生成」阶段完全缺失（最可能）

根据 `docs/issue/2026-04-11-frontend-workflow-issues.md` 中的分析，**`draft` 节点在 research graph 中完全缺失**。

```
当前 graph：
clarify → search_plan → review → persist_artifacts → END
              ↑
         没有 search
              ↑
         没有 draft（导致没有报告内容）

正确 graph：
clarify → search_plan → search → extract → draft → review → repair? → persist
```

报告内容是直接从某个节点输出而非通过 draft 节点生成的，导致：
- 只输出了一个模板化的框架（各 section 的标题）
- 没有调用 LLM 去真正「撰写」每个 section

#### 原因 B：Review 节点跳过了草稿阶段

如果 review 节点在没有任何 draft 内容的情况下就通过了，
会导致 `persist_artifacts` 直接输出了空的报告框架。

#### 原因 C：Draft 节点存在但 prompt 太弱

如果 draft 节点存在但没有正确引用已检索的论文内容，
可能导致生成空模板。

### 需要检查的文件

```
src/research/graph/builder.py              — research graph 中是否有 draft 节点
src/research/agents/analyst_agent.py       — 是否实现了 report drafting 逻辑
src/research/agents/supervisor.py           — draft → review 的流转逻辑
src/research/graph/nodes/                  — graph/nodes/ 下有哪些节点
```

---

## 五、问题 Q4：永远走 heuristic fast path

### 症状

日志输出：

```
Using heuristic fast path for a clear brief.
```

几乎每个任务都打印这条日志，无论 brief 复杂度。

### 可能原因

#### 原因 A：置信度阈值过低

`_should_use_fast_path()` 判断逻辑：

```python
confidence >= 0.6  # ← 这个阈值太低，几乎所有 brief 都满足
```

#### 原因 B：所有 LLM 调用都没有返回 thinking

如果模型没有开启 thinking mode，输出短且直接，会导致 confidence 虚高：

```
LLM 输出简短 → 误判为「brief 很清晰，不需要多轮」→ 走 fast path
```

#### 原因 C：所有节点的模型选择错误

如果 REASON_MODEL 也配置成了不支持 thinking 的快速模型，
整个 chain-of-thought 都会被截断。

### 需要检查的文件

```
src/research/policies/clarify_policy.py  — _should_use_fast_path() 阈值
src/agent/settings.py                     — REASON_MODEL / QUICK_MODEL 配置
src/agent/llm.py                          — LLM 调用时是否传递了 thinking 相关参数
```

---

## 六、综合根因分析

```
用户输入
    ↓
clarify → brief（可能因为未开启 thinking，内容很浅）
    ↓
search_plan → 生成的 queries 错误/搜索路径失效
    ↓
召回的论文完全不相关（与 topic 无关）
    ↓
draft 节点缺失 → 直接输出空模板报告
    ↓
review → 空报告通过（因为内容为空无法判断质量）
    ↓
persist_artifacts → 输出有结构但无实质内容的报告
```

**核心链路问题**：搜索结果质量差（Q2）是最先发生的故障点，导致后续所有内容都是「垃圾进垃圾出」。

---

## 七、问题关联图

```
Q2: 搜索不相关 ←←←←←←←┐
     ↓                        │
Q1: 未开 thinking            │  搜索不相关导致 draft 无好材料
     ↓                        │  Q3: 报告无内容
Q4: fast path ←←←←←←←←←┘
     ↓
     草稿阶段内容空洞
```

---

## 八、调试优先级建议

### Step 1：隔离 Q2（论文搜索问题）

单独测试 `SearchPlanAgent` 的查询生成和搜索结果：

```python
# 临时在 search_plan_agent.py 中添加
print(f"[DEBUG] Generated queries: {search_queries}")
print(f"[DEBUG] Search results: {results[:5]}")
```

验证 arXiv API 是否能搜到正确的 SWE Agent 论文。

### Step 2：确认 Q1（thinking 状态）

检查 LLM client 的初始化配置：

```python
# src/agent/llm.py
# 应该检查是否传入了：
llm_config = {
    "thinking": {"type": "enabled", "budget_tokens": 10000},
    # 而不是直接调用 chat completion
}
```

### Step 3：确认 graph 完整性

验证 research graph 中是否存在 `draft` 节点：

```python
from src.research.graph.builder import ResearchGraphBuilder
builder = ResearchGraphBuilder()
graph = builder.build()
print([n for n in graph.nodes])
# 应该包含：search, extract, draft
```

---

## 九、附：用户原始输入

```
「25年ai agent在软件工程swe agent的知名论文、benchmark、架构设计，未来发展」
```

### 预期召回的论文类型

- SWE-bench 相关：BROWSERGYM, SWE-bench, ToolBench, etc.
- Agent 架构：ReAct, Reflexion, AutoGPT, AutoGen, etc.
- 代码相关：Codex, CodeRL, AlphaCode, etc.
- Benchmark：BFCL, LiveCodeBench, etc.

### 实际召回的论文类型

- 语音处理（Voice Privacy Challenge）
- 天文（小行星 Asteroid 2024 BX1）
- 引力波
- 医疗影像（Kidney tumor segmentation, Aorta segmentation）
- 文档处理（DocILE, DocILE）

---

## 十、相关文档

- `docs/issue/2026-04-11-frontend-workflow-issues.md` — Research graph 缺失节点分析
- `docs/active/phase/phase2/` — Phase 2 规划（search→extract→draft→review 流程）

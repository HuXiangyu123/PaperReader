# SearchPlanAgent 设计文档

## 1. SearchPlanAgent 在整个系统里的定位

SearchPlanAgent 是 Phase 1 中**唯一需要实现为真实 Agent 的业务模块**。

它的唯一职责是：

> 把 ClarifyAgent 输出的结构化 ResearchBrief，转换为一个可执行的、结构化的 SearchPlan。

也就是说，它做的是：

- 理解研究目标，从 ResearchBrief 提取关键词和子问题
- 用工具（而非 LLM 直接生成）探索候选查询
- 维护工作记忆，记录每次搜索的命中数量、质量
- 反思当前覆盖范围，识别 gap
- 修订查询：扩展、改写、合并、去重
- 有界迭代（有预算控制），最终输出结构化 SearchPlan

**核心设计原则**：这是一个真实的 Agent 循环，而非一次性 JSON 生成器。

---

## 2. 为什么 SearchPlanAgent 需要是 Agent

Phase 1 有两个主要模块：ClarifyAgent 和 SearchPlanAgent。

它们的设计哲学不同：

| 模块 | 类型 | 原因 |
|------|------|------|
| ClarifyAgent | 固定结构节点 | 输入简单（用户需求），输出强 schema，只需一次 LLM 调用 |
| SearchPlanAgent | 真实 Agent 循环 | 目标复杂（多层次覆盖），需要工具观察、记忆、反思、迭代 |

SearchPlanAgent 必须成为 Agent，有五个原因：

1. **目标导向行为**：需要动态决定"查什么、从哪个角度查"
2. **工具调用**：搜索是外部 HTTP 调用，Agent 必须通过工具触发
3. **工作记忆**：每次搜索的结果、质量都需要持久化到下一次迭代
4. **反思/自纠正**：第一次生成的查询不一定是最好的，需要用分析工具检测 gap 后修订
5. **停止条件**：有预算（iteration budget）控制，不能无限搜索

---

## 3. SearchPlanAgent 适合的架构

四层结构：

```
Graph Node → Agent Service → Tool Runtime → SearchPlan
```

### 第一层：Graph Node

`src/research/graph/nodes/search_plan.py`

作用：
- 从 `ResearchState.brief` 取 ResearchBrief JSON
- 调用 Agent Service
- 将 `SearchPlanResult`（plan dict + warnings + stage）写回 state
- 处理异常，输出失败 stage

```python
def run_search_plan_node(state: dict) -> SearchPlanNodeOutput:
    brief = state.get("brief")
    result = run(brief)  # Agent Service
    return SearchPlanNodeOutput(
        search_plan=result.plan.model_dump(mode="json"),
        search_plan_warnings=result.warnings,
        current_stage="search_plan",
    )
```

### 第二层：Agent Service

`src/research/agents/search_plan_agent.py`

作用：
- 实现完整的 Agent 循环（见第 4 节）
- 调用 Tool Runtime 发起工具
- 维护 `SearchPlannerMemory`
- 输出 `SearchPlanResult`

### 第三层：Tool Runtime

`src/tools/registry.py` + `src/tools/search_tools.py`

作用：
- 提供工具函数注册表
- 通过 `@tool` 装饰器暴露 9 个 planning 工具
- 所有工具均通过 urllib 调用 SearXNG JSON API

### 第四层：SearchPlan Schema

`src/models/research.py` + `src/research/policies/search_plan_policy.py`

作用：
- 定义 `SearchPlan`、`SearchPlannerMemory`、`SearchPlanResult` 等模型
- 定义策略函数：`should_stop`、`to_fallback_plan`、`is_plan_valid`
- 严格 schema 校验，LLM 输出必须通过 Pydantic 校验

---

## 4. Agent 循环（核心）

SearchPlanAgent 运行以下循环，最多 10 次迭代：

```
┌─────────────────────────────────────────────┐
│  1. Initialize                                │
│     - 读取 ResearchBrief                       │
│     - 调用 expand_keywords 扩展关键词             │
│     - 初始化 memory                            │
├─────────────────────────────────────────────┤
│  2. Stop Check（迭代开始前）                    │
│     - remaining_budget ≤ 0 → STOP             │
│     - 已达 MAX_ITERATIONS → STOP               │
│     - 连续 2 次无改善 → STOP                    │
├─────────────────────────────────────────────┤
│  3. Observe（工具调用）                         │
│     - _propose_queries() 提议候选查询列表       │
│     - 调用 search_arxiv 观察结果                 │
│     - 更新 memory: attempted_queries,          │
│       query_to_hits, empty_queries             │
├─────────────────────────────────────────────┤
│  4. Reflect（分析工具调用）                     │
│     - summarize_hits：归纳当前覆盖主题           │
│     - detect_sparse_or_noisy_queries：         │
│       检测噪声和稀疏查询                        │
│     - 更新 memory: planner_reflections          │
├─────────────────────────────────────────────┤
│  5. Plan Generation（LLM 调用）                │
│     - 将 memory 注入 reflection_prompt          │
│     - LLM 决策：STOP / EXPAND / REFINE /       │
│       SEARCH_MORE                              │
│     - LLM 生成 / 更新 SearchPlan JSON           │
├─────────────────────────────────────────────┤
│  6. Stop Check（迭代结束后）                    │
│     - 所有查询均有命中 → STOP                   │
│     - 覆盖充分 → STOP                          │
│     - 否则进入下一次迭代                         │
└─────────────────────────────────────────────┘
        ↓
   STOP → 7. Emit SearchPlan
```

### 查询提议策略（_propose_queries）

根据 iteration 轮次提议不同的查询：

| Iteration | 策略 |
|-----------|------|
| 1 | 直接搜索主题 + 扩展关键词第一名 |
| 2 | 扩展关键词第二名 + survey + benchmark |
| 3 | 扩展关键词第三名 + application + limitation |
| 4+ | 针对 empty queries 和 coverage gap，用 expand_kw 后续词补查 |

每次提议前会做去重检查，已在 `attempted_queries` 中的跳过。

---

## 5. 工具集（Tool Runtime）

### 5.1 工具列表

| 工具名 | 类型 | 说明 |
|--------|------|------|
| `search_arxiv` | 查询探索 | 通过 SearXNG 调用 arXiv 搜索，返回论文列表 |
| `search_local_corpus` | 查询探索 | 在本地 PostgreSQL 语料库做 BM25 搜索 |
| `search_metadata_only` | 查询探索 | 仅返回论文元数据（标题、作者、年份） |
| `expand_keywords` | 查询扩展 | 调用 LLM 扩展主题关键词（同义词、上位词） |
| `rewrite_query` | 查询修订 | 调用 LLM 重写查询（精确/扩展/替代三种模式） |
| `merge_duplicate_queries` | 查询合并 | 调用 LLM 合并语义重复的查询列表 |
| `summarize_hits` | 覆盖率分析 | 调用 LLM 归纳当前搜索结果覆盖的主题 |
| `estimate_subquestion_coverage` | 覆盖率分析 | 评估搜索结果对各子问题的覆盖程度 |
| `detect_sparse_or_noisy_queries` | 质量分析 | 调用 LLM 检测稀疏查询和噪声结果 |

### 5.2 工具调用约定

所有工具通过 `@tool` 装饰器暴露为 LangChain Tool。Agent 内部调用时使用 `tool.invoke({"query": ...})` 模式。

工具返回值统一为字符串，由 Agent 自行解析。

### 5.3 SearXNG 引擎配置

- SearXNG 运行在 `http://127.0.0.1:8080`（Docker）
- search_arxiv 使用 `engines=arxiv`（避免多引擎并发超时）
- search_metadata_only 同样使用 `engines=arxiv`
- 不使用 `categories` 参数（SearXNG categories 与 engines 互斥）

---

## 6. 工作记忆（SearchPlannerMemory）

工作记忆是任务作用域的，不持久化到磁盘，仅在单次 SearchPlan 生成过程中维护。

| 字段 | 类型 | 说明 |
|------|------|------|
| `attempted_queries` | list[str] | 已执行过的所有查询 |
| `query_to_hits` | dict[str, int] | 每个查询的命中数量 |
| `empty_queries` | list[str] | 命中为 0 的查询 |
| `high_noise_queries` | list[str] | 被判定为噪声的查询 |
| `subquestion_coverage_map` | dict[str, list[str]] | 子问题 → 覆盖它的查询 |
| `source_usage_stats` | dict[str, int] | 各来源引擎使用统计 |
| `planner_reflections` | list[str] | 反思阶段的分析记录 |
| `iteration_count` | int | 当前迭代轮次 |
| `remaining_budget` | int | 剩余迭代预算（初始 10） |
| `last_action` | str | 上一步动作（search/expand/rewrite/stop） |
| `last_hits` | int | 上一步的总命中数 |

---

## 7. 策略函数（Policy）

位于 `src/research/policies/search_plan_policy.py`。

### 7.1 is_plan_valid(plan)

校验 SearchPlan 是否满足最低质量：

- `plan_goal` 非空
- `query_groups` 非空
- 所有 group 内查询数之和 > 0

### 7.2 should_stop(memory, plan)

判断是否应停止，返回 `(bool, str)`：

| 条件 | 停止？ | 理由 |
|------|--------|------|
| `remaining_budget ≤ 0` | 是 | 预算耗尽 |
| `iteration_count ≥ 10` | 是 | 最大迭代次数 |
| 连续 2 次无改善 | 是 | 边际收益递减 |
| 所有查询均有命中 | 是 | 覆盖充分 |
| 其他 | 否 | 继续搜索 |

### 7.3 to_fallback_plan(brief)

当 LLM 调用失败或无法解析有效 JSON 时，从 ResearchBrief 提取 `topic` 和 `keywords` 生成最保守的兜底 plan：

- 一个 broad query_group
- 包含 topic + keywords[:5]
- `followup_needed = true`（提醒下游可能需要补充搜索）
- `planner_warnings` 记录降级原因

---

## 8. Schema 设计

### 8.1 SearchPlan

```python
class SearchPlan(BaseModel):
    schema_version: str = "v1"
    plan_goal: str                     # 搜索计划的核心目标
    coverage_strategy: CoverageStrategy # broad | focused | hybrid
    query_groups: list[SearchQueryGroup]
    source_preferences: list[str]
    dedup_strategy: DedupStrategy       # exact | semantic | none
    rerank_required: bool = True
    max_candidates_per_query: int = 30
    requires_local_corpus: bool = False
    coverage_notes: str = ""
    planner_warnings: list[str] = []
    followup_search_seeds: list[str] = []
    followup_needed: bool = False
```

### 8.2 SearchQueryGroup

```python
class SearchQueryGroup(BaseModel):
    group_id: str
    queries: list[str]
    intent: str          # 查询意图：broad/focused/background
    priority: int = 1    # 1=最高
    expected_hits: int = 20
    notes: str = ""
```

### 8.3 SearchPlanResult

```python
class SearchPlanResult(BaseModel):
    plan: SearchPlan
    memory: SearchPlannerMemory
    warnings: list[str]
    raw_model_output: str | None  # 原始 LLM 输出（调试用）
```

---

## 9. Fallback 行为

| 失败场景 | 行为 |
|---------|------|
| 关键词扩展工具失败 | 记录 warning，使用原始 topic 继续 |
| search_arxiv 调用失败 | 记录到 planner_reflections，跳过该查询 |
| 反思阶段异常 | 吞掉异常，记录 warning，继续下一阶段 |
| LLM JSON 解析失败 | 记录 warning，降级到 policy fallback plan |
| LLM 调用本身异常 | 记录 warning，降级到 policy fallback plan |
| 所有迭代均无有效 plan | 最终使用 to_fallback_plan() |

Fallback plan 均会在 `planner_warnings` 中留下记录，下游可以感知到 plan 是降级生成的。

---

## 10. 外部依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| SearXNG | Docker latest | 学术搜索后端（HTTP JSON API） |
| PostgreSQL | 17 | 语料库元数据存储 |
| LangChain | 最新 | @tool 装饰器、Chat model 接口 |
| Pydantic | v2 | Schema 定义与校验 |
| SQLAlchemy | 2.0 | PostgreSQL ORM |

---

## 11. 当前实现状态

| 组件 | 文件 | 状态 |
|------|------|------|
| Agent Service | `src/research/agents/search_plan_agent.py` | ✅ 完整实现（含工具调用、记忆、反思、策略） |
| Prompt 模板 | `src/research/prompts/search_plan_prompt.py` | ✅ 完整实现 |
| 策略函数 | `src/research/policies/search_plan_policy.py` | ✅ 完整实现 |
| Graph Node | `src/research/graph/nodes/search_plan.py` | ✅ 完整实现 |
| Tool Runtime | `src/tools/specs.py` / `registry.py` | ✅ 完整实现 |
| 9 个工具 | `src/tools/search_tools.py` | ✅ 完整实现（SearXNG + 本地语料库） |
| Schema | `src/models/research.py` | ✅ 完整实现 |
| 研究 Graph Builder | `src/research/graph/builder.py` | ✅ 已更新 |
| 测试 | `tests/` | ⏳ 待补充 |

---

## 12. 待补充

### 12.1 测试（tests/）

需覆盖以下场景：

| 测试场景 | 说明 |
|---------|------|
| `test_clear_brief_success` | 正常 ResearchBrief，成功生成 SearchPlan |
| `test_ambiguous_brief_followup` | 歧义 brief，`followup_needed=True` |
| `test_empty_query_handling` | 空查询不重复调用 |
| `test_tool_failure_fallback` | 工具失败时降级到 policy fallback |
| `test_malformed_output_fallback` | LLM 输出格式错误时降级 |
| `test_budget_stopping` | `remaining_budget=0` 时停止 |
| `test_iteration_stopping` | 达到 `MAX_ITERATIONS` 时停止 |
| `test_schema_validation` | 生成的 plan 通过 Pydantic 校验 |

### 12.2 本地语料库工具完善

`search_local_corpus` 当前依赖 `HybridSearcher`，但 FAISS 向量索引尚未构建（`data/indexes/` 目录为空）。在有 ingestion 数据后需要：

1. 初始化 FAISS 索引：`python -m src.retrieval.build_index`
2. 将索引路径配置到 `.env`：`FAISS_INDEX_PATH=...`

### 12.3 PaperCard 提取节点

SearchPlan 完成后，下游会接入 `PaperCardExtractor` 节点（不在本文档范围内）。

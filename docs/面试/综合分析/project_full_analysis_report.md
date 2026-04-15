# PaperReader Agent — 项目全仓库深度分析报告

> 本报告基于 `review_plan.md` 的 16 维框架，对 PaperReader Agent 项目进行全仓库扫描与深度分析。
> 分析日期：2026-04-12 | 分析范围：`src/`、`frontend/`、`eval/`、`tests/`、`docs/` 及根目录配置文件

---

## 1. 项目概览

### 1.1 项目定位

**PaperReader Agent** 是一个面向科研场景的多阶段 LLM Agent 系统，核心功能是：用户输入研究主题（如"调研医疗垂类大模型中的 AI agent 发展"），系统自动完成**需求澄清 → 检索规划 → 多源论文获取 → 结构化抽取 → 综述生成 → Review 把关 → 报告持久化**的全流程，最终输出带可追溯引用的结构化 Markdown 综述报告。

这不是一个单步调用的 RAG demo，也不是一个简单的"输入链接输出摘要"的单 Agent 脚本，而是一个具备以下特征的真实系统：

- **多阶段 StateGraph 工作流**（Research Graph + Report Graph 双图并行）
- **Multi-Agent 协作**（ClarifyAgent、SearchPlanAgent、ReviewerAgent、Supervisor）
- **结构化输出 + 引用验证闭环**（citation resolve → claim verify → policy apply）
- **PostgreSQL 持久化**（任务快照、报告、向量 chunk）
- **前端可视化 + SSE 实时推送**（GraphView、TraceTimeline、ReviewFeedbackPanel）
- **三层 Eval 评测体系**（hard rules → LLM grounding judge → human review）

### 1.2 业务背景

科研人员/研究生在写综述论文时，面临的核心痛点是：
- 需要从数十篇乃至上百篇论文中提取方法、数据集、贡献、局限
- 手工整理引用关系耗时且容易出错
- 生成的综述报告缺少引用可靠性验证（幻觉风险）

PaperReader Agent 试图解决这个问题：自动化地从用户模糊的研究主题出发，通过 planner 澄清需求、多源检索获取论文、结构化抽取 paper cards、跨文献综合生成报告，并在报告生成后做 claim-level 的引用可靠性验证。

### 1.3 目标用户

- 研究生、博士生的综述写作场景
- 科研团队需要对某一技术方向做快速调研
- 对报告质量有引用可追溯性要求的研究者

### 1.4 为什么它不是普通脚本 / 普通问答 / 普通 RAG demo

| 维度 | 普通 RAG | 本项目 |
|------|----------|--------|
| 输入形态 | 静态文档库 | 动态研究主题 + 多源实时检索 |
| 输出形态 | QA 对话 | 结构化综述报告 + 引 用验证 |
| 流程控制 | 单次检索→生成 | 7 节点 StateGraph（clarify→search_plan→search→extract→draft→review→persist）|
| 引用验证 | 无 | claim-level grounding + source tier 分类 |
| 多模态 | 无 | 支持 arXiv URL / PDF 上传 / 研究主题 |
| 持久化 | 无 | PostgreSQL 持久化任务快照、报告、向量 chunk |
| 可视化 | 无 | 前端 GraphView + SSE 实时节点状态推送 |

### 1.5 当前仓库实现成熟度判断

综合 `docs/current-architecture-and-usage.md` 及代码扫描结果：

**Phase 1-3 已落地**（核心流程可用）：
- ✅ Research Graph：7 节点全链路贯通（clarify → search_plan → search → extract → draft → review → persist_artifacts）
- ✅ Report Graph：11 节点单篇论文报告图（保留 legacy 向后兼容）
- ✅ ClarifyAgent + SearchPlanAgent（Phase 1 planner 层）
- ✅ 三源并行检索（SearXNG + arXiv API + DeepXiv）
- ✅ 批量 LLM 抽取 PaperCards（3 篇/批）
- ✅ ReviewerService + grounding pipeline（resolve_citations → verify_claims → format_output）
- ✅ Source Tier 分类（A/B/C/D 四级权威度）
- ✅ PostgreSQL 持久化（TaskSnapshot + Report + ChunkStore）
- ✅ 前端 React 19 + TypeScript + @xyflow/react 可视化
- ✅ Skill 框架（SkillOrchestrator + SkillsRegistry + MCPAdapter）

**Phase 4 部分实现**：
- ⚠️ MCPAdapter 已写好 stdio/HTTP transport 框架，但实际调用的 MCP server 数量为零
- ⚠️ SkillOrchestrator 的 implicit 模式（LLM 决定 skill chain）存在但未在前端暴露
- ⚠️ Multi-Agent 分工（planner/retriever/analyst/reviewer）已在 registry 中定义角色，但 orchestrator 层较弱

**待完善**：
- ❌ Re-plan 机制缺失（clarify 失败或 review 失败时无法自动重新规划）
- ❌ DAG 级别并行 fan-out（当前并行只在节点内部，节点间仍为串行）
- ❌ Chunk Store 的向量检索（PostgreSQL + pgvector 未配置，向量搜索用 FAISS）
- ❌ Mutation testing / deterministic replay
- ❌ CI 中 LLM 依赖的 Layer 2/3 eval 未运行（Layer 1 eval gate 存在但不执行）

---

## 2. 前沿工程共识总结

### 2.1 Anthropic 对 Agent 系统的核心判断（2024-12）

基于 Anthropic 官方博客 *Building Effective Agents* 的关键结论：

**核心原则：简单可组合 > 复杂框架**

1. **Workflow vs Agent 的区分**：Workflow 是预定义路径的编排（适合明确任务），Agent 是 LLM 动态决定下一步（适合开放任务）。本项目处于两者之间：Graph 是预定义的（workflow），但每个节点内部有 LLM 驱动的决策（部分 agentic）。

2. **推荐的 Agent 架构模式**（Anthropic 经验）：
   - **Prompt Chaining**：每步处理前一步输出 → 本项目的 Graph 编排方式
   - **Router/Orchestrator-Workers**：中央 LLM 分解任务并委托 → 本项目的 Supervisor/ClarifyAgent
   - **Evaluator-Optimizer**：生成→评审→迭代 → 本项目的 draft→review 循环
   - **Parallelization**：独立子任务并行 → 本项目 search_node 内部的 SearXNG/arxiv/deepxiv 并行

3. **Agent 成功的三个核心原则**：
   - 保持设计简单（Complexity = Enemy of Reliability）
   - 显式展示规划步骤（Transparency）
   - **精心设计 Agent-Computer Interface（ACI）**：工具定义要像写给 junior developer 的文档，要做 poka-yoke（防错设计）

4. **框架的态度**：用框架快速起步，但最终要穿透抽象层理解底层代码。本项目用 LangGraph + LangChain 起步，但通过 `instrument_node`、`NodeEventEmitter` 等自研包装层掌握了执行控制权。

### 2.2 成熟 Agent 系统的关键要素（判断基线）

| 要素 | 成熟标志 | 本项目现状 |
|------|----------|-----------|
| **Workflow / Orchestration** | 可视化 DAG、可配置分支/重试、超时控制 | ✅ DAG 可视化（@xyflow/react）、conditional edges、degradation_mode |
| **Reasoning / Planning** | Planner 节点、re-plan 机制 | ⚠️ ClarifyAgent 存在，re-plan 缺失 |
| **Tools / Function Calling** | 工具注册表、schema 版本、调用追踪 | ✅ ToolRuntime + ToolSpec 注册；⚠️ schema 版本管理缺失 |
| **MCP** | MCP Client SDK、标准 transport、tools/prompts/resources | ✅ MCPAdapter 完整实现 stdio+HTTP transport；⚠️ 实际 MCP server 未接入 |
| **Skills** | prompt bundle/workflow/toolchain 封装、可复用 | ✅ SkillsRegistry + 5 个 ARIS 风格 skills；⚠️ 实际调用链路不完整 |
| **Memory / State / History** | 短/长期记忆分离、向量检索 | ⚠️ PostgreSQL 持久化存在；向量 chunk 未检索 |
| **Structured Outputs** | Pydantic schema、JSON 约束、重试协议 | ✅ 全链路 Pydantic v2 |
| **Lifecycle Control** | launch/run/pause/retry/cancel、状态序列化 | ⚠️ cancel 是标记式（非真正线程中止） |
| **Harness Engineering** | runtime harness、middleware、long-running 管理 | ✅ instrument_node + NodeEventEmitter；⚠️ 无 middleware 层 |
| **Eval / Benchmark** | retrieval eval、agent eval、regression、smoke | ✅ Layer 1+2 eval；⚠️ Layer 2/3 未在 CI 中执行 |
| **Trace / Observability** | per-node traces、tool calls、token 追踪 | ✅ trace_wrapper + NodeEventEmitter + SSE events |

---

## 3. 仓库结构与主工作流总览

### 3.1 目录结构

```
PaperReader_agent/
├── src/
│   ├── agent/               # 旧版 ReAct agent + LLM 封装 + settings
│   │   ├── llm.py          # build_reason_llm / build_quick_llm / build_chat_llm
│   │   ├── report.py       # generate_literature_report（legacy）
│   │   ├── settings.py     # 全局 Settings 单例（多 provider 支持）
│   │   └── cli.py          # 交互式 CLI 入口
│   ├── api/
│   │   └── routes/
│   │       ├── tasks.py    # 核心任务 API（POST /tasks, /tasks/{id}, /events, /chat, /trace, /review）
│   │       ├── report.py   # legacy 单次报告 API
│   │       └── workspaces.py
│   ├── graph/              # Report Graph（11 节点单篇报告图）
│   │   ├── state.py        # AgentState TypedDict
│   │   ├── builder.py      # build_report_graph()
│   │   ├── callbacks.py    # NodeEventEmitter（SSE + trace）
│   │   ├── instrumentation.py  # instrument_node（计时 + 事件发射）
│   │   └── nodes/          # 11 个节点实现
│   │       ├── input_parse.py
│   │       ├── ingest_source.py
│   │       ├── extract_document_text.py
│   │       ├── normalize_metadata.py
│   │       ├── retrieve_evidence.py
│   │       ├── draft_report.py
│   │       ├── repair_report.py
│   │       ├── resolve_citations.py
│   │       ├── verify_claims.py
│   │       ├── apply_policy.py
│   │       └── format_output.py
│   ├── research/           # Research Graph（7 节点综述调研图）
│   │   ├── graph/
│   │   │   ├── state.py   # 与 graph/state.py 共用 AgentState
│   │   │   ├── builder.py # build_research_graph()
│   │   │   └── nodes/
│   │   │       ├── clarify.py
│   │   │       ├── search_plan.py
│   │   │       ├── search.py    # 三源并行检索 + ingest
│   │   │       ├── extract.py   # 批量 LLM 抽取
│   │   │       ├── draft.py     # LLM 综合 + fallback
│   │   │       ├── review.py    # grounding pipeline 集成
│   │   │       └── persist_artifacts.py
│   │   ├── agents/
│   │   │   ├── clarify_agent.py
│   │   │   ├── search_plan_agent.py
│   │   │   ├── supervisor.py
│   │   │   ├── retriever_agent.py
│   │   │   ├── planner_agent.py
│   │   │   └── reviewer_agent.py
│   │   ├── services/
│   │   │   ├── reviewer.py      # ReviewerService（4 类检查）
│   │   │   └── grounding.py     # ground_draft_report（pipeline 桥接）
│   │   ├── policies/
│   │   │   ├── clarify_policy.py
│   │   │   └── search_plan_policy.py
│   │   └── prompts/
│   │       ├── clarify_prompt.py
│   │       └── search_plan_prompt.py
│   ├── corpus/           # 文档处理与检索
│   │   ├── models.py     # CoarseChunk / FineChunk / PaperCard
│   │   ├── store/
│   │   │   └── chunk_store.py  # PostgreSQL ChunkStore
│   │   ├── search/
│   │   │   ├── corpus_search.py
│   │   │   ├── paper_retriever.py
│   │   │   ├── chunk_retriever.py
│   │   │   ├── deduper.py
│   │   │   ├── reranker.py      # CrossEncoderReranker
│   │   │   ├── evidence_typer.py
│   │   │   └── result_builder.py
│   │   └── ingest/
│   │       ├── chunkers.py
│   │       ├── parsers.py
│   │       ├── loaders.py
│   │       ├── coarse_chunker.py
│   │       ├── fine_chunker.py
│   │       └── ...
│   ├── db/              # SQLAlchemy 2 ORM + PostgreSQL
│   │   ├── engine.py     # get_session_factory
│   │   ├── models.py     # ORM models（Document, CoarseChunk, FineChunk, TaskSnapshot, Report）
│   │   └── task_persistence.py
│   ├── retrieval/
│   │   ├── citations.py
│   │   └── search.py
│   ├── tools/           # 工具层
│   │   ├── registry.py  # ToolRuntime 全局注册表
│   │   ├── specs.py    # ToolSpec
│   │   ├── arxiv_api.py
│   │   ├── arxiv_paper.py
│   │   ├── search_tools.py   # SearXNG search wrapper
│   │   ├── rag_search.py    # 本地 RAG search
│   │   ├── web_fetch.py
│   │   ├── pdf.py
│   │   ├── local_fs.py
│   │   ├── mcp_adapter.py   # MCPAdapter（MCP stdio+HTTP transport）
│   │   └── deepxiv_client.py
│   ├── skills/         # Skill 框架
│   │   ├── registry.py  # SkillsRegistry（4 种 backend handler）
│   │   ├── orchestrator.py  # SkillOrchestrator（explicit/implicit 模式）
│   │   ├── discovery.py
│   │   ├── runner.py
│   │   └── research_skills.py  # 5 个 ARIS 风格 skill 函数
│   ├── models/         # Pydantic domain models
│   │   ├── paper.py
│   │   ├── report.py   # DraftReport / Claim / Citation / FinalReport / GroundingStats
│   │   ├── task.py    # TaskRecord / TaskStatus
│   │   ├── review.py   # ReviewFeedback / ReviewIssue / CoverageGap
│   │   ├── mcp.py     # MCPServerConfig / MCPToolDescriptor / ...
│   │   ├── skills.py  # SkillManifest / SkillRunRequest / SkillRunResponse
│   │   ├── agent.py   # AgentRole enum
│   │   └── workspace.py
│   ├── tasking/
│   │   └── trace_wrapper.py  # trace_node / trace_tool 装饰器
│   ├── verification/   # 引用验证层
│   │   ├── claim_judge.py
│   │   ├── reachability.py
│   │   └── source_tiers.py
│   └── validators/
│       └── citations_validator.py
├── frontend/           # React 19 + TypeScript + Tailwind CSS 4
│   └── src/
│       ├── components/
│       │   ├── TaskSubmitForm.tsx
│       │   ├── GraphView.tsx       # @xyflow/react DAG 可视化
│       │   ├── ToolLogPanel.tsx
│       │   ├── ProgressBar.tsx
│       │   ├── ReportPreview.tsx
│       │   ├── TaskHistory.tsx
│       │   ├── AgentPanel.tsx
│       │   ├── ChatPanel.tsx
│       │   ├── ConfigPanel.tsx
│       │   ├── SessionOverview.tsx
│       │   ├── ReviewFeedbackPanel.tsx
│       │   ├── ResearchFollowupForm.tsx
│       │   ├── MarkdownRenderer.tsx
│       │   ├── ThinkingPanel.tsx
│       │   ├── TraceTimeline.tsx
│       │   ├── Phase34Panel.tsx
│       │   └── SkillPalette.tsx
│       ├── hooks/
│       │   ├── useTaskSSE.ts
│       │   └── useTaskDetail.ts
│       └── types/
│           ├── task.ts
│           └── phase34.ts
├── eval/               # 三层评测体系
│   ├── runner.py
│   ├── gate.py
│   ├── diff.py
│   ├── cases.jsonl    # 20 个评测 case
│   ├── layers/
│   │   ├── hard_rules.py    # Layer 1
│   │   └── grounding.py     # Layer 2（claim support rate / citation resolution / abstention compliance）
│   └── promptfoo.yaml
├── tests/             # pytest 测试套件
│   ├── api/          # API 层测试
│   ├── graph/        # Graph 节点测试
│   │   └── nodes/    # 各节点的单元测试
│   ├── corpus/       # Corpus 层测试（ingest + search + store）
│   ├── eval/         # Eval 评测测试
│   ├── research/     # Research graph 测试
│   ├── verification/ # 引用验证测试
│   ├── models/       # Model 测试
│   ├── conftest.py
│   ├── test_e2e.py
│   └── test_integration_cli.py
└── .agents/skills/  # Skill 定义文件
    ├── claim_verification/SKILL.md
    ├── comparison_matrix_builder/SKILL.md
    ├── experiment_replicator/SKILL.md
    ├── lit_review_scanner/SKILL.md
    └── writing_scaffold_generator/SKILL.md
```

### 3.2 核心入口

**API 层**：`src/api/routes/tasks.py`
- `POST /tasks` → 创建任务 + 调度 `_schedule_task_run(task_id)` 到 ThreadPoolExecutor
- `GET /tasks/{id}` → 查询任务快照（含所有中间产物）
- `GET /tasks/{id}/events` → SSE 实时推送节点事件
- `GET /tasks/{id}/result` → 获取最终报告（含 resolved/verified/final report）
- `GET /tasks/{id}/trace` → 返回完整 node runs + tool runs + events
- `GET /tasks/{id}/review` → 返回 ReviewFeedback
- `POST /tasks/{id}/chat` → skill 命令或普通对话

**图构建**：
- `src/research/graph/builder.py::build_research_graph()` → 编译 Phase 1-3 7 节点 Research Graph
- `src/graph/builder.py::build_report_graph()` → 编译 11 节点 Report Graph（legacy）

### 3.3 主流程

**Research Graph 流程（`/tasks` 走 research 模式）**：

```
用户输入研究主题
  ↓
clarify_node（ClarifyAgent + clarify_policy）
  → 生成 ResearchBrief（topic / goal / sub_questions / desired_output / inclusion_criteria / ambiguities）
  → 如 needs_followup=True → 路由到 END（需追问澄清）
  ↓
search_plan_node（SearchPlanAgent + search_plan_policy）
  → 生成 SearchPlan（query_groups / plan_goal / time_range / warnings）
  ↓
search_node（三源并行：SearXNG + arXiv API + DeepXiv）
  → ThreadPoolExecutor(max_workers=3) 并行
  → 优先级合并去重（arXiv > DeepXiv > SearXNG）
  → enrich_search_results_with_arxiv 批量补充 metadata
  → _ingest_paper_candidates：前 50 篇写入 PostgreSQL ChunkStore
  → 产出 RagResult（含 paper_candidates）
  ↓
extract_node（批量 LLM 抽取 PaperCards）
  → 3 篇/批并行抽取
  → 构建 PaperCard 结构（title/authors/methods/datasets/summary）
  ↓
draft_node（LLM 综合 + fallback 模板）
  → _build_draft_report：8-section 结构化 DraftReport（title/abstract/introduction/background/taxonomy/methods/datasets/evaluation/discussion/future_work/conclusion）
  → _inject_citation_content：用 paper_cards 的 abstract 填充 citation.fetched_content
  → _build_markdown：渲染为可读 Markdown
  ↓
review_node（ReviewerService + grounding pipeline）
  → ground_draft_report（resolve_citations → verify_claims → format_output）
  → ReviewerService.review：4 类检查（paper_cards 质量 / 覆盖性 / claim 支撑 / citation reachability / 结构重复）
  → 产出 ReviewFeedback（issues / coverage_gaps / claim_supports / revision_actions）
  ↓
persist_artifacts_node（PostgreSQL + workspace artifact）
  → 持久化所有中间产物到数据库
```

**Report Graph 流程（`/report` 走 legacy 单篇模式）**：

```
输入 arXiv URL/ID 或 PDF bytes
  ↓
input_parse → ingest_source → extract_document_text → normalize_metadata（对称 ingestion）
  ↓
retrieve_evidence（rag_search + web_fetch 并行）
  ↓
draft_report → repair_report → resolve_citations → verify_claims → apply_policy → format_output
```

### 3.4 关键模块职责

| 模块 | 核心职责 | 关键文件 |
|------|----------|----------|
| **Research Graph** | 7 节点调研工作流编排 | `src/research/graph/builder.py` |
| **ClarifyAgent** | 需求澄清 + ResearchBrief 生成 | `src/research/agents/clarify_agent.py` |
| **SearchPlanAgent** | 查询规划 + SearchPlan 生成 | `src/research/agents/search_plan_agent.py` |
| **Search Node** | 三源并行检索 + 去重 + ingest | `src/research/graph/nodes/search.py` |
| **Extract Node** | 批量 LLM paper card 抽取 | `src/research/graph/nodes/extract.py` |
| **Draft Node** | 结构化报告综合 + fallback | `src/research/graph/nodes/draft.py` |
| **Review Node** | 引用验证 + 质量闸门 | `src/research/graph/nodes/review.py` |
| **Grounding Service** | cite resolve → claim verify → format | `src/research/services/grounding.py` |
| **ReviewerService** | 4 类质量检查 | `src/research/services/reviewer.py` |
| **ToolRuntime** | 工具注册 + 统一调用接口 | `src/tools/registry.py` |
| **MCPAdapter** | MCP stdio+HTTP transport | `src/tools/mcp_adapter.py` |
| **SkillsRegistry** | 4 种 backend handler skill 执行 | `src/skills/registry.py` |
| **SkillOrchestrator** | explicit/implicit skill 路由 | `src/skills/orchestrator.py` |
| **ChunkStore** | PostgreSQL coarse/fine chunk 持久化 | `src/corpus/store/chunk_store.py` |
| **CrossEncoderReranker** | 本地语义重排 | `src/corpus/search/reranker.py` |
| **NodeEventEmitter** | SSE + trace 事件发射 | `src/graph/callbacks.py` |
| **instrument_node** | 节点包装（计时+事件+异常捕获）| `src/graph/instrumentation.py` |
| **trace_wrapper** | trace_node/trace_tool 装饰器 | `src/tasking/trace_wrapper.py` |
| **Source Tier** | A/B/C/D 权威度分类 | `src/verification/source_tiers.py` |
| **Eval Runner** | Layer 1+2 评测执行 | `eval/runner.py` |
| **Task Persistence** | PostgreSQL 快照持久化 | `src/db/task_persistence.py` |

---

## 4. 业务需求与 Story 设计分析

### 4.1 业务场景

PaperReader Agent 面向的是**学术综述写作**这一垂直场景。用户场景路径：

1. **输入**：用户输入一个模糊的研究主题（如"AI Agent 在医疗领域的进展"）
2. **澄清**：系统通过 ClarifyAgent 追问子问题、时间范围、期望输出格式
3. **规划**：SearchPlanAgent 生成多组查询策略（覆盖核心方法/数据集/最新进展）
4. **检索**：三源并行获取候选论文，去重后前 50 篇自动入库
5. **抽取**：批量 LLM 抽取每篇论文的结构化 paper card
6. **综合**：LLM 综合所有 paper cards 生成 8-section 结构化综述
7. **验证**：引用 resolve → claim verify → policy apply，标记不可靠 claim
8. **交付**：持久化到 PostgreSQL，前端可预览 + 对话追问 + 导出 Markdown

### 4.2 输入输出矩阵

| 输入类型 | `source_type` | 处理路径 | 典型输出 |
|----------|---------------|----------|----------|
| arXiv URL/ID | `arxiv` | Report Graph（11 节点）| 带引用的 Markdown 报告 |
| PDF 文件 bytes | `pdf` | Report Graph（对称 ingestion）| 带引用的 Markdown 报告 |
| 研究主题文本 | `research` | Research Graph（7 节点）| 结构化综述 + ReviewFeedback |

### 4.3 当前 Story 的完整性评估

**已闭环的部分**：
- ✅ Research Graph 7 节点全链路贯通
- ✅ 引用验证闭环（cite resolve → claim verify → policy apply → abstention markers）
- ✅ 任务持久化（TaskSnapshot + Report + ChunkStore）
- ✅ SSE 实时推送

**缺口**：
- ❌ Review 失败后没有自动 revise 节点（review_node 返回 `review_passed=False` → 直接 END）
- ❌ Clarify 阶段的需求追问没有通过前端交互式完成（ClarifyAgent 内部有 `needs_followup` 逻辑但未对接前端）
- ❌ 无连续调研上下文（workspace 之间的跨任务记忆缺失）

---

## 5. Agent 架构与 Workflow 设计分析

### 5.1 单 Agent 还是 Multi-Agent

**判断：准 Multi-Agent，有分工但无动态协作层**

当前系统中存在多个 Agent 角色：
- **ClarifyAgent**（`src/research/agents/clarify_agent.py`）：需求澄清
- **SearchPlanAgent**（`src/research/agents/search_plan_agent.py`）：查询规划
- **Supervisor**（`src/research/agents/supervisor.py`）：任务编排
- **ReviewerAgent**（`src/research/agents/reviewer_agent.py`）：质量评审

但它们的实现方式是：
1. **嵌入 Graph 节点**：每个 Agent 是一个 `run_*_node` 函数，不是独立的进程/线程
2. **串行执行**：clarify → search_plan → search → extract → draft → review → persist，按序执行
3. **共享状态**：通过 `AgentState` TypedDict 共享所有中间产物

**这不是真正的 Multi-Agent 并行协作**，更接近 **Agent-Enhanced Workflow**（每个节点背后有一个 LLM Agent，但决策空间受限于节点边界）。

### 5.2 Workflow / Graph / Orchestrator 组织

```
┌─────────────────────────────────────────────────────┐
│              Research Graph (7 节点)                │
│                                                     │
│  clarify ──→ search_plan ──→ search ──→ extract    │
│                      │              │              │
│                      │              ↓              │
│                      │           draft ──→ review  │
│                      │              │         │    │
│                      ↓              ↓         ↓    │
│                    END         persist   END（若失败）│
└─────────────────────────────────────────────────────┘
```

路由策略：
- `clarify` → `needs_followup=True` → END（需追问）
- `review` → `review_passed=True` → `persist_artifacts`；否则 → END

**Conditional Edges** 是 LangGraph 原生支持的路由，但目前所有条件判断都极其简单（只有布尔路由），没有更复杂的基于 LLM 的动态分支。

### 5.3 Reasoning / Planning / Re-plan

| 能力 | 现状 | 评估 |
|------|------|------|
| **Clarify（需求澄清）** | ClarifyAgent 通过 policy 生成 ResearchBrief，含 ambiguities 和 needs_followup | ✅ 已实现 |
| **SearchPlan（规划）** | SearchPlanAgent 生成 query_groups，支持 heuristic 和 agent 两种模式 | ✅ 已实现 |
| **Re-plan（重规划）** | 无。当 clarify/search_plan 失败或 review 失败时，路由到 END，没有回退或重新规划 | ❌ 缺失 |
| **反思（Reflection）** | 无显式 reflection 机制。review_node 可以发现问题，但不会驱动重写 | ❌ 缺失 |

### 5.4 Review / Loop / Verify

| 能力 | 现状 | 评估 |
|------|------|------|
| **Review 节点** | ReviewerService + grounding pipeline | ✅ 完整 |
| **Verify-Optimize Loop** | 无。review_node 生成 feedback，但无 revise 节点 | ❌ 缺失 |
| **Iterative Refinement** | draft_node 失败时有 template fallback，但 report 本身无重写循环 | ⚠️ 部分 |
| **Claim-Level Grounding** | resolve_citations → verify_claims → apply_policy 三段式 | ✅ 完整 |

### 5.5 是"真正 Agent"还是"Workflow + Tool Calling"

**判断：更接近 "Workflow + Tool Calling"，但比纯 Workflow 有更多 Agentic 特征**

理由：
- ✅ Graph 拓扑是预定义的（workflow），不是完全由 LLM 动态决定
- ✅ 但节点内部有 LLM 驱动的决策（ClarifyAgent 的 ambiguities 判断、SearchPlanAgent 的 query 生成）
- ✅ 存在 degradation_mode（`normal / limited / safe_abort`）条件降级
- ✅ instrument_node 提供了 per-step 的观测能力
- ❌ 无真正的 ReAct/Plan-and-Execute 循环
- ❌ LLM 不决定下一个节点是什么（路由是代码控制的）

**对标**：Anthropic 的分类中，这属于 **Prompt Chaining + Evaluator-Optimizer** 的混合模式。

---

## 6. Agent 技术细节分析

### 6.1 Reasoning

**实现方式**：通过 LLM 的 Chain-of-Thought 隐式推理。

在 `ClarifyAgent` 和 `SearchPlanAgent` 中，系统提示词要求 LLM "think step by step" 或直接生成结构化输出。`build_reason_llm` 默认使用 `reason_model`（支持 DeepSeek Reasoner / GPT-4 等推理模型），而非纯 chat 模型。

**局限**：没有显式的 **Chain-of-Thought 中间结果持久化**。`NodeEventEmitter.on_thinking()` 存在但只在 `instrument_node` 中被调用（且只在有 `_reasoning_content` 时），实际推理过程未结构化记录。

### 6.2 Plan / Execute / Re-plan

**Plan**：SearchPlanAgent 生成 `SearchPlan`，包含：
- `plan_goal`：搜索目标描述
- `query_groups`：多组查询，每组有 `group_id / intent / queries / expected_hits`
- `time_range`：时间范围
- `warnings`：规划警告

**Execute**：Graph 按序执行各节点。

**Re-plan**：❌ 完全缺失。这是当前最大的架构缺口。当 `clarify` 生成了 `needs_followup=True`、或 `search` 没有返回任何论文、或 `review` 发现 blocker 级别问题时，系统直接 END，不会重新规划。

### 6.3 Tools 调用方式

**注册层**（`src/tools/registry.py` → `ToolRuntime`）：
```python
runtime = get_runtime()
runtime.register_function(name, func, spec)
result = runtime.invoke(tool_name, **kwargs)  # → ToolResult
```

**工具列表**（`src/tools/`）：
| 工具 | 用途 | 调用方式 |
|------|------|----------|
| `_searxng_search` | SearXNG 搜索 | 直接 import 函数 |
| `search_arxiv_direct` | arXiv API | 直接 import |
| `search_papers`/`get_trending_papers` | DeepXiv | 直接 import |
| `rag_search` | 本地向量搜索 | 直接 import |
| `fetch_webpage_text` | 网页抓取 | 直接 import |
| `extract_text_from_pdf_bytes` | PDF 解析 | 直接 import |

**关键观察**：工具通过 `register_function` 注册到 `ToolRuntime`，但 Graph 节点中**大多数工具是直接 import 函数调用的**，没有通过 `ToolRuntime.invoke()` 统一接口。这意味着：
- 工具的调用路径不统一（有的走 registry，有的不走）
- 重试/降级逻辑散落在各处
- 无统一的 tool call trace

### 6.4 State 管理

**状态载体**：`AgentState` TypedDict，通过 `Annotated[..., operator.add]` 支持 `tokens_used` 和 `warnings` 的累加。

**状态流转**：每个节点接收 `state: dict`，返回 `dict` patch（只更新自己的输出字段），通过 LangGraph 的状态合并机制更新。

**状态持久化**：
- 内存：`src/api/routes/tasks.py::_tasks` dict（`{task_id: TaskRecord}`）
- PostgreSQL：`src/db/task_persistence.py::upsert_task_snapshot`
- Chunk：`src/corpus/store/chunk_store.py`

### 6.5 输出结构化程度

**极强**：全链路 Pydantic v2 模型约束。

关键 Schema：
- `DraftReport(sections: dict, claims: list[Claim], citations: list[Citation])`
- `Claim(id, text, citation_labels, supports: list[ClaimSupport], overall_status)`
- `Citation(label, url, reason, source_tier, reachable, fetched_content)`
- `GroundingStats(total, grounded, partial, ungrounded, abstained, tier_a_ratio, tier_b_ratio)`
- `FinalReport(sections, claims, citations, grounding_stats, report_confidence)`
- `ReviewFeedback(task_id, passed, issues, coverage_gaps, claim_supports, revision_actions, summary)`
- `ReviewIssue(severity, category, target, summary, evidence_refs)`

### 6.6 Review / Reflection / Verification

**Review**：ReviewerService 四类检查（paper_cards 质量 / 覆盖性 / claim 支撑 / citation reachability / 结构重复）。

**Reflection**：无显式 reflection 节点，但 ReviewerService 产生的 `revision_actions`（`RevisionAction`）包含了 `RESEARCH_MORE / DROP_CLAIM / FIX_CITATION / REWRITE_SECTION` 等行动建议。

**Verification**：`grounding.py::ground_draft_report()` 串联三个 legacy 节点：
1. `resolve_citations`：URL 可达性检查 + source tier 分类
2. `verify_claims`：LLM judge claim-evidence 配对
3. `format_output`：应用 policy + 渲染最终 Markdown

---

## 7. Context Engineering 分析

### 7.1 Prompt Engineering

**集中管理**：prompts 分散在两处：
- `src/research/prompts/`：`clarify_prompt.py`、`search_plan_prompt.py`
- `src/research/graph/nodes/draft.py`：内联了超长 system prompt（draft 生成的 JSON schema）

**Prompt 版本控制**：❌ 无显式版本控制。prompt 文本内联在函数中，变更无审计追踪。

**动态 Prompt 注入**：`draft_node` 的 system prompt 包含 `brief_ctx`（topic + sub_questions + desired_output），通过 `_build_brief_context` 动态构建。

### 7.2 RAG

**三层检索架构**（`search_node` 实现）：
1. **SearXNG**（广度召回）：多查询并行，`ThreadPoolExecutor(max_workers=8)`，搜 `arxiv` engine
2. **arXiv API**（精度）：每查询取 10 条，并行执行
3. **DeepXiv**（补充 + 热度）：前 3 核心词 + trending 热门论文

**去重策略**：优先级 arXiv > DeepXiv > SearXNG，基于 `arxiv_id + url` 精确去重。

**向量检索**：⚠️ `ChunkStore` 存在，但实际检索未使用（`_ingest_paper_candidates` 写入了 abstract chunks，但 `rag_search` 从未调用这些 chunks）。

**Cross-Encoder Reranker**：`src/corpus/search/reranker.py` 实现了 `CrossEncoderReranker`：
- 模型：`cross-encoder/ms-marco-MiniLM-L-6-v2`（轻量、速度快）
- `rerank()` API：`query + candidates → reranked by cross-encoder scores`
- `rerank_with_fusion()`：RRF + Cross-Encoder 加权融合（默认 40% RRF + 60% rerank）
- ⚠️ 但 `search_node` 的最终排序**未调用 reranker**，候选论文按 dedup 顺序直接返回

### 7.3 Memory

**短期记忆**：Graph State（`AgentState` TypedDict）贯穿整个任务生命周期。

**长期记忆**：
- PostgreSQL 持久化（TaskSnapshot、Report、ChunkStore）
- `.memory/` 目录（semantic + episodic，均为 JSON 格式，不参与主流程）

### 7.4 State / History

**状态**：`AgentState` TypedDict 是唯一的运行时状态载体。

**历史**：`TaskRecord.chat_history` 支持多轮对话（`/chat` endpoint），但历史仅用于 `/chat` endpoint 的上下文注入，不参与 Research Graph 的重规划。

### 7.5 Structured Outputs

**强约束**：
- `draft_node` 的 LLM 调用要求输出严格 JSON（`"The output MUST be strictly valid JSON (no markdown code blocks)"`）
- `_extract_json()` 解析函数处理 markdown code block 包裹、裸 JSON 对象、裸 JSON 数组三种格式
- fallback 机制：当 LLM JSON 解析失败时，构造基于 cards 的 template-based draft
- `_inject_citation_content` 修复：解决 draft 生成的 citations 缺少 `fetched_content` 的问题

### 7.6 Context Loading / Passing / Compaction

**Loading**：输入通过 `_build_state_template` 初始化，所有字段显式 None。

**Passing**：LangGraph 自动通过状态传递，每个节点返回 patch dict。

**Compaction**：❌ 无显式 context compaction。当 paper cards 数量超过 30 篇时（`cards[:30]`），直接截断而非压缩。

### 7.7 Retrieval as Context

**实现**：`search_node` 的 `RagResult` 包含 `paper_candidates` + `evidence_chunks`（目前为 `[]`），但这些数据通过 `AgentState.rag_result` 传递给下游节点（extract/draft）。

**问题**：`evidence_chunks` 始终为空（`search_node` 产出的 chunk 写入了 DB 但未写入 RagResult）。

### 7.8 Workspace Artifacts as Context

**实现**：`persist_artifacts_node` 将所有中间产物写入 workspace。

**前端消费**：`GET /tasks/{id}/result` 返回 `resolved_report` + `verified_report` + `final_report`，前端通过 `BriefCard` / `SearchPlanCard` / `PaperCardsSection` / `DraftPreview` / `ReviewFeedbackCard` 组件渲染。

---

## 8. Multi-Agent 设计分析

### 8.1 Orchestrator 层

**Supervisor**（`src/research/agents/supervisor.py`）：存在但未在 Graph 中作为独立节点使用。

**真正的 Orchestrator**：`src/api/routes/tasks.py::_run_graph_sync_wrapper`（约 120 行），负责：
- 根据 `source_type` 选择 Research Graph 或 Report Graph
- 初始化状态模板
- 调用 `graph.stream(initial_state)`
- 处理结果并写入 TaskRecord

**判断**：这不是一个 LLM 驱动的动态 orchestrator，而是**代码硬编码的条件路由**。当需要新增一种 workflow 时，必须修改 `_run_graph_sync_wrapper`。

### 8.2 Workers 层

| Worker | 角色 | 边界清晰度 |
|--------|------|-----------|
| ClarifyAgent | 需求澄清 → ResearchBrief | ✅ 边界清晰 |
| SearchPlanAgent | 查询规划 → SearchPlan | ✅ 边界清晰 |
| ReviewerAgent | 质量闸门 → ReviewFeedback | ✅ 边界清晰 |
| RetrieverAgent | 检索（但实际走 search_node 函数） | ⚠️ agent 定义存在，未使用 |
| PlannerAgent | 规划（但实际走 SearchPlanAgent） | ⚠️ agent 定义存在，未使用 |
| AnalystAgent | 分析（对应 extract_node） | ⚠️ agent 定义存在，未使用 |

**问题**：大多数 Agent 类（`retriever_agent.py`、`planner_agent.py`、`analyst_agent.py`）是空壳或仅定义了 prompt，实际执行路径走的是对应的 graph node 函数（`search_node`、`clarify_node` 等）。

### 8.3 Shared State / Artifacts

✅ **清晰**：`AgentState` TypedDict 是所有 agent 的共享状态，类型安全（Pydantic）。

✅ **可持久化**：`TaskRecord` 对齐所有状态字段，`upsert_task_snapshot` 持久化到 PostgreSQL。

✅ **Schema 统一**：`src/models/` 下所有 domain model 统一使用 Pydantic v2。

### 8.4 总体判断

**当前项目是"概念性 Multi-Agent"，而非"工程实现的 Multi-Agent"**：

- 角色定义存在（AgentRole enum、5 个 agent 文件）
- 但实际执行路径是函数调用，不是 agent 间通信
- 无 agent 间消息传递机制
- 无 agent 级别的超时/重试/降级

**建议**：如果要真正做成 multi-agent，应该：
1. 每个 agent 是独立可运行的 LLM 调用（有 system prompt + tool set）
2. agent 间通过共享的 workspace 状态通信
3. Supervisor 基于 LLM 动态分配任务（而非代码路由）

---

## 9. Function Calling / Tools 分析

### 9.1 Tool Schema

**定义**：`src/tools/specs.py::ToolSpec`，包含 name / description / category / input_schema。

**注册**：`src/tools/registry.py::ToolRuntime.register_function(name, func, spec)`。

**使用**：Graph 节点中大多数工具是**直接 import 函数**，不通过 registry。这种做法：
- ✅ 简单直接
- ❌ 工具调用无统一 trace
- ❌ 无法动态替换/拦截工具
- ❌ tool registry 的价值被浪费

### 9.2 Tool Registry / Tool Runtime

`ToolRuntime`（`src/tools/registry.py`）：
```python
class ToolRuntime:
    def register_function(name, func, spec)
    def invoke(tool_name, **kwargs) -> ToolResult  # 统一返回 ToolResult
    def list_registered() -> list[str]
```

**问题**：registry 存在但几乎没人用。`_searxng_search`、`search_arxiv_direct`、`enrich_search_results_with_arxiv` 等核心工具都直接 import 调用。

### 9.3 Function Calling Loop

**Report Graph** 中的 function calling：通过 `create_react_agent`（legacy）或节点内直接调用（新版）。

**Research Graph** 中：**无 ReAct 风格的 function calling loop**。各节点直接调用工具函数，没有 LLM 动态选择工具的循环。

**这与设计的 trade-off**：Anthropic 的研究表明，ReAct 风格的 function calling 适合**开放任务**（无法预测需要哪些工具），而 PaperReader 的 workflow 是**预定义任务**（每个节点需要哪些工具是固定的）。所以不走 function calling loop 是合理的设计选择。

### 9.4 输入输出约束

**统一约束**：`ToolResult` TypedDict（`ok / output / error / tool_name / latency_ms`）。

**错误处理**：`tool 调用 → try/except → 返回 ToolResult(ok=False, error=...)`。异常不外泄。

### 9.5 Timeout / Retry / Fallback

| 能力 | 实现 | 评估 |
|------|------|------|
| **LLM timeout** | `build_reason_llm(..., timeout_s=240)` | ✅ `draft_node` 设置 240s |
| **HTTP timeout** | 30s（`enrich_search_results_with_arxiv`） | ✅ |
| **重试** | ❌ 无统一重试机制（`resolve_citations` 无 retry） | ❌ |
| **Fallback** | ✅ `draft_node` 有 LLM → template fallback | ✅ |
| **降级（Degradation）** | ✅ `degradation_mode: normal/limited/safe_abort` | ✅ |

### 9.6 Trace / Observability

✅ **完整**：`instrument_node` 包装每个节点：
- 计时（`duration_ms`）
- token 消耗（`tokens_delta`）
- 警告列表（`warnings`）
- 错误（`error`）
- reasoning 内容（`_reasoning_content`）

✅ **SSE**：`NodeEventEmitter` 通过 `asyncio.Queue` 推送事件到 `/tasks/{id}/events`。

✅ **trace_store**：`src/tasking/trace_wrapper.py` 的 `trace_node`/`trace_tool` 装饰器。

### 9.7 权限 / Auth / 调用边界

- LLM API Key 通过 `.env` 配置（`DEEPSEEK_API_KEY` 等），`get_settings()` 统一读取
- 数据库连接通过 `DATABASE_URL`（PostgreSQL only）
- SearXNG 通过 `SEARXNG_BASE_URL` 配置
- ⚠️ 无 API 层面的认证（`/tasks` 等 endpoint 无 auth middleware）

---

## 10. MCP / Skills 分析

### 10.1 MCP

**实现**：`src/tools/mcp_adapter.py`（353 行，完整实现）：

| 组件 | 实现状态 | 细节 |
|------|----------|------|
| **Transport（stdio）** | ✅ | `StdioTransport`：通过 `subprocess.Popen` 启动 MCP server，JSON-RPC over stdin/stdout |
| **Transport（HTTP）** | ✅ | `RemoteHttpTransport`：通过 httpx 发送 JSON-RPC POST |
| **Capability Discovery** | ✅ | `_discover_capabilities()` 发现 tools/prompts/resources |
| **Tool Invocation** | ✅ | `MCPServerInstance._invoke_tool()` |
| **Prompt Invocation** | ✅ | `MCPServerInstance._invoke_prompt()` |
| **Resource Invocation** | ✅ | `MCPServerInstance._invoke_resource()` |
| **Server Lifecycle** | ✅ | `start() / stop() / is_running` |
| **Multi-Server** | ✅ | `MCPAdapter` 管理多个 `MCPServerInstance` |
| **实际 MCP Server** | ❌ | 没有任何 MCP server 被实际注册或调用 |

**与工具层的关系**：`MCPToolchainHandler`（`src/skills/registry.py`）可以将 MCP tool 桥接为 `SkillBackend.MCP_TOOLCHAIN`。

**Schema**：`src/models/mcp.py` 定义了 `MCPServerConfig / MCPToolDescriptor / MCPPromptDescriptor / MCPResourceDescriptor / MCPInvokeKind / MCPInvocationRequest / MCPInvocationResponse`。

### 10.2 Skills

**注册体系**（`src/skills/registry.py`）：

4 种 backend handler：
| Handler | Backend | 说明 |
|---------|---------|------|
| `LocalGraphHandler` | `LOCAL_GRAPH` | 调用 LangGraph 节点函数 |
| `LocalFunctionHandler` | `LOCAL_FUNCTION` | 直接调用 Python 函数 |
| `MCPToolchainHandler` | `MCP_TOOLCHAIN` | 通过 MCP adapter 调用 |
| `MCPPromptHandler` | `MCP_PROMPT` | 通过 MCP 获取 prompt |

**内置 Skills**（9 个）：
| Skill ID | 名称 | Backend | 默认 Agent |
|----------|------|---------|-----------|
| `lit_review_scanner` | Literature Review Scanner | LOCAL_FUNCTION | RETRIEVER |
| `paper_plan_builder` | Paper Plan Builder | LOCAL_FUNCTION | ANALYST |
| `creative_reframe` | Creative Reframe | LOCAL_FUNCTION | PLANNER |
| `workspace_policy_skill` | Workspace Policy Skill | LOCAL_FUNCTION | SUPERVISOR |
| `claim_verification` | Claim Verification | LOCAL_FUNCTION | REVIEWER |
| `comparison_matrix_builder` | Comparison Matrix Builder | LOCAL_FUNCTION | ANALYST |
| `experiment_replicator` | Experiment Replicator | LOCAL_FUNCTION | ANALYST |
| `writing_scaffold_generator` | Writing Scaffold Generator | LOCAL_FUNCTION | ANALYST |
| `research_lit_scan` | Research Literature Scan | LOCAL_FUNCTION | RETRIEVER |

**发现机制**：`SkillsRegistry.discover_from_filesystem()` 扫描 `.agents/skills/` 和 `.claude/skills/`，解析 `SKILL.md` 文件生成 `SkillManifest`。

**SkillOrchestrator**（`src/skills/orchestrator.py`）：
- **Explicit 模式**：`/skill_id args...` → 直接路由到对应 skill
- **Implicit 模式**：LLM 决定使用哪些 skill 和顺序（`_llm_decide_tools`）
- ⚠️ Implicit 模式的 LLM decision prompt 较简陋（`build_quick_llm` + 1024 max_tokens）

**复用价值**：✅ Skills 有清晰的 `SkillManifest`（名称/描述/backend/输入 schema），可组合成 chain。

**前端调用**：✅ `/tasks/{id}/chat` 支持 `/skill_id args` 语法。

---

## 11. Lifecycle Control 与 Harness Engineering 分析

### 11.1 Lifecycle Control

| 能力 | 实现 | 评估 |
|------|------|------|
| **Launch** | `POST /tasks` → `TaskRecord` → `_schedule_task_run()` | ✅ |
| **Run** | `ThreadPoolExecutor` 执行 `_run_graph_sync_wrapper` | ✅ |
| **Pause** | ❌ 无 | ❌ |
| **Resume** | ❌ 无 | ❌ |
| **Retry** | ❌ 无自动重试（`terminate` 是标记式） | ❌ |
| **Cancel** | ⚠️ `terminate_task` 是标记式（设置 `status=FAILED, error="Terminated by user"`），无法真正中止线程 | ⚠️ |
| **State Serialization** | ✅ `upsert_task_snapshot` → PostgreSQL JSONB | ✅ |
| **Async Continuation** | ⚠️ `asyncio.to_thread(_run_graph_sync, ...)` 但实际走 ThreadPoolExecutor | ⚠️ |
| **从中断点恢复** | ❌ 无。TaskRecord 持久化了状态但 `_run_graph_sync` 无法从中间节点恢复 | ❌ |
| **Task ID / Workspace ID** | ✅ `task_id`（UUID）、`workspace_id`（`ws_{task_id[:12]}`） | ✅ |

### 11.2 Harness Engineering

**Runtime Harness**：
- `instrument_node` 是最核心的 harness：计时 + 事件发射 + 异常捕获 + reasoning 捕获
- `trace_node`/`trace_tool` 装饰器提供细粒度 trace

**Middleware / Wrapper**：
- ⚠️ 无独立的 middleware 层（异常处理、监控、限流都在节点内）
- 但 `instrument_node` 事实上充当了 middleware 的角色

**Long-Running Agent 管理**：
- SSE endpoint（`/tasks/{id}/events`）通过 `asyncio.Queue` 推送实时状态
- ⚠️ 无超时强制中止（LLM 调用可能 hang，240s timeout 在 `draft_node` 有，但其他节点无）
- ⚠️ 并发任务数量无显式限制（`ThreadPoolExecutor(max_workers=4)` 但未做 queue 长度控制）

**Session / Context 持续化**：✅ PostgreSQL 持久化 + `.memory/` 目录（semantic + episodic）。

**Trace / Event / Execution Logging**：
- ✅ `NodeEventEmitter` 事件列表追加到 `task.node_events`
- ✅ `trace_wrapper` 的 `TraceStore`（`src/tasking/trace_wrapper.py`）
- ✅ `eval/runs/` 目录保存每次评测的 trace JSON

**生命周期 API 控制**：
- ✅ `POST /tasks/{id}/terminate`
- ❌ 无 `pause` / `resume` / `retry`

---

## 12. 代码设计分析

### 12.1 模块划分

**分层清晰**：
```
API Layer          → FastAPI routes
  ↓
Graph Layer        → StateGraph（Research + Report 双图）
  ↓
Agent Layer        → ClarifyAgent / SearchPlanAgent / ReviewerAgent
  ↓
Service Layer      → ReviewerService / GroundingService
  ↓
Tool Layer         → ToolRuntime / MCPAdapter / Search Tools
  ↓
Corpus Layer       → ChunkStore / Search / Reranker
  ↓
DB Layer           → SQLAlchemy 2 ORM + PostgreSQL
```

**模块间依赖**：`src/research/` 依赖 `src/graph/`（共用 `AgentState`、`instrument_node`）、`src/tools/`、`src/models/`、`src/corpus/`、`src/db/`、`src/verification/`。依赖方向单向无环（除了 `src/research/graph/nodes/search.py` 内 import 了 `src/corpus/store/chunk_store`）。

### 12.2 核心抽象

| 抽象 | 实现 | 质量评估 |
|------|------|----------|
| `AgentState` (TypedDict) | 统一状态载体 | ✅ 类型安全 |
| `NodeStatus` (Pydantic) | 节点状态追踪 | ✅ |
| `ToolResult` (TypedDict) | 工具返回标准化 | ✅ |
| `DraftReport / FinalReport` | 报告结构 | ✅ Pydantic |
| `ReviewFeedback` | 质量反馈 | ✅ |
| `SkillManifest / SkillRunRequest` | Skill 抽象 | ✅ |
| `MCPServerConfig / MCPToolDescriptor` | MCP 抽象 | ✅ |
| `ChunkStore` | 存储抽象 | ✅ |
| `CrossEncoderReranker` | 检索抽象 | ✅ |

### 12.3 Schema / Model / Storage / Service / API

**Schema**：`src/models/` 全 Pydantic v2，与 FastAPI 集成。

**Storage**：`PostgreSQL only`（SQLAlchemy 2，`.sqlite` 文件被明确禁止）。

**Service**：`src/research/services/` 下有 `reviewer.py`（ReviewerService）和 `grounding.py`（ground_draft_report 函数），业务逻辑封装良好。

**API**：`src/api/routes/tasks.py`（1123 行），是整个后端最复杂的文件。职责较多（任务管理 + SSE + Chat + Model Config + 调试端点），可以考虑拆分。

### 12.4 耦合度

**合理耦合**：
- Graph 节点通过 `AgentState` 通信，低耦合
- Services 层独立于 Graph 层
- DB 层通过 session factory 访问

**需要关注的耦合**：
- `src/research/graph/nodes/draft.py` 内联了超长 system prompt（约 200 行），应抽取到 `prompts/` 目录
- `src/api/routes/tasks.py`（1123 行）过于庞大，包含 7 个 endpoint + 3 个 helper + 调试端点
- `_run_graph_sync_wrapper` 和 `_run_graph_sync` 重复逻辑较多

### 12.5 可维护性

**优点**：
- 类型标注完整（Pydantic + TypedDict）
- 每个节点有 `@trace_node` 装饰器
- 文档字符串基本覆盖

**风险点**：
- `src/tools/search_tools.py` 的 `_searxng_search` 是模块级裸函数，无类封装
- `src/research/graph/nodes/draft.py` 的 `_fallback_draft` 是手工构造的硬编码模板，当 LLM 失败时内容质量极低
- `_inject_citation_content` 是 workaround 性质的修复，不解决根本问题（draft LLM prompt 本身没有要求输出 fetched_content）

### 12.6 扩展性

**好扩展**：
- 新增 Graph 节点：只需 `g.add_node()` + `g.add_edge()`
- 新增 Tool：`register_function()`
- 新增 Skill：`SkillManifest` + backend function
- 新增 MCP server：`MCPAdapter.register()`

**难扩展**：
- 新增 Graph 类型（目前只有 Report 和 Research 两个）：需要修改 `_run_graph_sync_wrapper`
- 新增一种 source_type：需要修改 `_run_graph_sync_wrapper` 的 if/else 分支

---

## 13. 量化指标 / Eval / Benchmark 分析

### 13.1 Retrieval Eval

**现状**：
- `tests/corpus/search/` 目录有 10+ 个检索相关测试
- `test_candidate_builder.py` / `test_deduper.py` / `test_reranker.py` / `test_paper_retriever.py`
- `test_chunk_retriever.py` / `test_evidence_typer.py`

**问题**：
- ⚠️ 这些是**单元测试**，不是 retrieval eval（离线 ground truth 评测）
- 无 retrieval benchmark 数据集
- `rag_search` 的召回质量没有量化评估
- `CrossEncoderReranker` 有 `is_available` 检测但 `search_node` 未调用

### 13.2 Reviewer Eval

**现状**：
- `tests/research/` 有 `test_supervisor.py`、`test_clarify_agent.py`、`test_search_plan_policy.py`
- `test_review_node.py`、`test_clarify_node.py`、`test_search_plan_node.py`
- `tests/verification/test_claim_judge.py`、`test_reachability.py`、`test_source_tiers.py`

**问题**：
- ⚠️ 大多数是 mock/fixture-based 单元测试，不是端到端 quality eval
- `ReviewerService._check_duplication_consistency()` 是空实现（`return [], []`）
- 无 ReviewFeedback 质量的 ground truth 标注

### 13.3 Workflow Eval

**现状**：
- `tests/test_e2e.py`（端到端）
- `tests/test_e2e_clarify.py`（clarify 流程）
- `tests/test_integration_cli.py`

**问题**：
- ⚠️ 依赖真实 LLM API，无法在 CI 中完整运行
- 无 regression test（评测结果对比）
- 无 smoke test（核心路径快速检查）

### 13.4 Benchmark / Regression / Smoke

**Benchmark**：
- `eval/cases.jsonl`：20 个评测 case（8 single arXiv + 4 single PDF + 3 sequential + 3 claim-evidence gold + 2 boundary）
- 包含 `expected_min_tier1_ratio`、`known_claims` 等 ground truth

**Layer 1（hard rules）**：`eval/layers/hard_rules.py`
- `check_structure`：必需 section 存在性
- `check_citation_format`：引用格式
- `check_must_include`：关键词
- `check_min_citations`：最少引用数
- `check_cost_guard`：token 预算

**Layer 2（grounding）**：`eval/layers/grounding.py`
- `check_claim_support_rate`（≥60% grounded → pass）
- `check_citation_resolution_rate`（≥70% reachable → pass）
- `check_unsupported_claim_count`（≤3 ungrounded → pass）
- `check_abstention_compliance`
- `check_source_tier_ratio`（≥30% Tier A → pass）

**Layer 3（human）**：无代码实现（`eval/layers/human.py` 不存在）

**Regression**：`eval/diff.py` 计算跨 run 的 pass rate delta。

**Smoke**：❌ 无独立 smoke test suite。

### 13.5 Golden Set / Eval Cases

✅ `eval/cases.jsonl`：20 个 case，格式规范，包含 `known_claims` 用于 claim-level 评测。

⚠️ 但 `eval/runner.py` 中的 `run_eval` 只调用 `generate_literature_report`（legacy 单篇 API），**不覆盖 Research Graph**。

### 13.6 版本对比

✅ `eval/diff.py` 有跨 run 对比逻辑（`diffs.md`）。

### 13.7 评测是否足够支撑项目演进

**判断：不够**。主要原因：
1. Layer 2 依赖 LLM judge，CI 中不执行（`"Skipping in CI — no DEEPSEEK_API_KEY"`）
2. Research Graph 评测完全缺失
3. Retrieval eval 依赖单元测试，不是离线 benchmark
4. 无 smoke test 快速检查核心路径

**建议补的 benchmark / metric**：
- Research Graph 端到端评测（clarify → draft 完整路径）
- Retrieval recall@K / MRR 评测（基于 `eval/cases.jsonl` 的 ground truth papers）
- Grounding quality 追踪（每版报告的 claim_support_rate / tier_a_ratio 趋势图）
- Latency per-node 追踪（识别慢节点）
- Token cost per-task 追踪

---

## 14. 软件工程与软件测试分析

### 14.1 测试覆盖矩阵

| 类别 | 测试文件数 | 覆盖内容 | 评估 |
|------|-----------|----------|------|
| **Unit - Corpus** | ~12 | ingest / search / store / reranker / deduper | ✅ 较完整 |
| **Unit - Graph Nodes** | ~14 | 11 report graph nodes + research nodes | ✅ 较完整 |
| **Unit - Research** | ~5 | clarify_agent / supervisor / policies | ✅ |
| **Unit - Verification** | ~3 | claim_judge / reachability / source_tiers | ✅ |
| **Unit - Models** | ~2 | paper / report Pydantic models | ✅ |
| **Integration** | ~4 | API / CLI / E2E | ⚠️ 依赖真实 API |
| **Eval** | ~3 | runner / gate / diff | ⚠️ 依赖 LLM |
| **CI** | `ci.yml` | pytest + npm build | ⚠️ LLM eval skip |

### 14.2 测试方法分析

| 方法 | 现状 |
|------|------|
| **Unit Test** | ✅ pytest + fixtures，大量使用 `conftest.py` 共享 fixtures |
| **Integration Test** | ⚠️ `tests/api/` 和 `tests/test_integration_cli.py` 存在 |
| **E2E Test** | ⚠️ `tests/test_e2e.py` 存在，但依赖真实 LLM API |
| **Mock / Stub / Fake** | ⚠️ 有 `conftest.py` fixtures，但 mock 使用不系统 |
| **AST-based Static Analysis** | ❌ 无 |
| **Golden Test** | ⚠️ `eval/cases.jsonl` 可视为 golden dataset，但无 `tests/golden/` 实际使用 |
| **Contract Test** | ❌ 无 |
| **Mutation Testing** | ❌ 未提及 |
| **Flaky Tests** | ❌ 无检测机制 |
| **Deterministic Replay** | ❌ 无（涉及 workflow / trace） |

### 14.3 CI Test Gates

`.github/workflows/ci.yml`：
```yaml
# Backend
python -m pytest tests/ -v --tb=short
# Frontend
npm run build
# Layer 1 eval (注释状态)
# "Layer 1 eval would run here with real API keys"
# "Skipping in CI — no DEEPSEEK_API_KEY"
```

**问题**：
- Layer 2/3 eval 完全不在 CI 中
- pytest 覆盖了 unit test，但 CI 通过 ≠ LLM quality 达标
- 无 regression gate（`-2%` 阈值在 CI 中未执行）

### 14.4 最值得优先补的测试

1. **Research Graph E2E smoke test**：3-5 个 case 快速验证 7 节点链路
2. **Retrieval recall benchmark**：基于 `eval/cases.jsonl` 的 ground truth papers 计算 recall@20
3. **Golden test for draft output**：用 `tests/golden/` 存放期望的 draft report snippet
4. **Flaky test detection**：重复运行 E2E test N 次，标记不稳定的 case
5. **AST-based code analysis**：检查 `src/research/graph/nodes/` 中是否有死代码

---

## 15. 面试价值总结

### 15.1 最值得讲的技术亮点

1. **多阶段 StateGraph 工作流设计**：7 节点 Research Graph + 11 节点 Report Graph，conditional edges + degradation mode，节点可独立测试
2. **引用验证闭环（Claim-Level Grounding）**：resolve_citations → verify_claims → apply_policy 三段式 + source tier A/B/C/D + abstention markers
3. **三源并行检索**：SearXNG + arXiv API + DeepXiv + 优先级去重 + CrossEncoderReranker
4. **三层 Eval 体系**：hard rules → LLM judge → human review，release gate 设计
5. **PostgreSQL-only 持久化策略**：`TaskSnapshot + Report + ChunkStore`，与 SQLite 的严格边界
6. **前端 Graph 可视化**：@xyflow/react + SSE 实时节点状态推送

### 15.2 最容易被追问的地方

1. **为什么用 LangGraph 而不是自己写 orchestrator？** → LangGraph 的 conditional edges + state 管理 + compile 机制省了大量代码，团队选择是合理的
2. **Multi-Agent 在哪里？** → 当前是"Agent-Enhanced Workflow"，ClarifyAgent/SearchPlanAgent 是 graph node 不是独立 agent
3. **为什么 Skill framework 有两层（Orchestrator + Registry）但只用了一层？** → Phase 4 MCP 部分还没接真实 server
4. **Review 失败后怎么处理？** → 目前直接 END，没有 revise 节点
5. **Vector retrieval 在哪里？** → ChunkStore 写入了但 `rag_search` 实际未从本地 chunks 检索
6. **Re-plan 机制呢？** → 不存在

### 15.3 最容易被质疑的地方

1. **"这是一个 workflow，不是一个 agent"**：Graph 拓扑是预定义的，LLM 不决定下一个节点
2. **"CrossEncoderReranker 实现了但没用"**：`search_node` 产出了候选但没 rerank
3. **"Eval 的 Layer 2/3 都没跑"**：CI 中跳过，报告质量没有自动化监控
4. **"ReviewerService._check_duplication_consistency 是空实现"**：4 类检查中最后 1 类是空壳
5. **"很多 Agent 文件是空壳"**：`retriever_agent.py`、`planner_agent.py`、`analyst_agent.py` 定义存在但实际路径不走这些

### 15.4 如何更稳地表述

- ✅ "我们设计了一个多阶段 StateGraph 工作流"（而不是"我们做了一个 agent"）
- ✅ "每节点可独立测试，通过 instrument_node 包装统一注入 trace"（而不是"我们用了 LangGraph"）
- ✅ "引用验证的 claim-level grounding 是参考了 SWE-bench 的验证思路"（具体指出参考）
- ✅ "三层 Eval 体系参考了 OpenAI Evals 的 design"（有据可查）
- ⚠️ "Skill framework" → 准确说"Separate skill registry from orchestrator, MCP adapter is Phase 4"

---

## 16. 未来优化建议

### 16.1 Workflow / Agent Architecture

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **增加 revise 节点** | 🔴 高 | review 失败时驱动草稿重写，形成 draft→review→revise→review 循环 |
| **支持 re-plan** | 🔴 高 | clarify 或 search 失败时，ClarifyAgent 重新生成 ResearchBrief |
| **Supervisor 升级为 LLM 驱动的 orchestrator** | 🟡 中 | 当前是代码路由，升级为 LLM 决定下一步 |
| **DAG 级别并行 fan-out** | 🟡 中 | 用 LangGraph 的 `Send` API 实现 extract 的 paper-level 并行 |

### 16.2 Context Engineering

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **抽取 draft prompt 到 prompts/ 目录** | 🔴 高 | `src/research/prompts/draft_system_prompt.py`，版本化管理 |
| **接入 CrossEncoderReranker** | 🔴 高 | `search_node` 最终排序调用 reranker |
| **实现 context compaction** | 🟡 中 | 当 cards > 30 时，做摘要压缩而非直接截断 |
| **接入 pgvector** | 🟡 中 | 当前 FAISS 未配置，PostgreSQL pgvector 可统一存储 |
| **Prompt 版本控制** | 🟡 中 | commit hash → prompt version → eval run 关联 |

### 16.3 Multi-Agent

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **Agent 间通过 workspace 通信** | 🔴 高 | 而不是通过函数调用 |
| **真实 RetrieverAgent/AnalystAgent** | 🔴 高 | 当前是空壳，升级为独立可运行的 LLM agent |
| **Skill implicit 模式优化** | 🟡 中 | 当前 LLM decision prompt 较简陋 |

### 16.4 Tools / Function Calling

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **统一工具调用路径** | 🔴 高 | 所有工具通过 `ToolRuntime.invoke()` 调用，统一 trace |
| **工具级重试协议** | 🔴 高 | `resolve_citations` 增加 HTTP retry（3次 + exponential backoff） |
| **工具超时统一配置** | 🟡 中 | 通过 `ToolSpec.timeout` 声明，instrument_node 统一拦截 |

### 16.5 MCP / Skills

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **接入至少一个真实 MCP server** | 🔴 高 | 如 `mcp-server-fetch` / `mcp-server-sql` |
| **前端 SkillPalette 完善** | 🟡 中 | 当前 `SkillPalette.tsx` 存在但未接入实际 skill 调用 |
| **MCP resources 作为 context** | 🟡 中 | MCP resource 可作为 retrieval context |

### 16.6 Lifecycle / Harness

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **真正可中止任务** | 🔴 高 | 用 `asyncio.Task.cancel()` 而非标记式 termination |
| **任务超时强制中止** | 🔴 高 | 每个节点 LLM 调用加 timeout |
| **从中断点恢复** | 🟡 中 | 持久化 `current_stage`，重启后可从该节点恢复 |
| **并发任务数量控制** | 🟡 中 | `max_concurrent_tasks` 配置 |

### 16.7 Eval / Benchmark

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **Research Graph E2E smoke test** | 🔴 高 | 3-5 case 快速验证 7 节点 |
| **Retrieval recall benchmark** | 🔴 高 | ground truth papers → recall@20 |
| **CI 中执行 Layer 2 eval（用 mock LLM）** | 🟡 中 | 不依赖真实 API key |
| **Flaky test detection** | 🟡 中 | 重复运行检测不稳定 case |
| **Latency per-node 追踪** | 🟡 中 | 识别慢节点（search_node 通常最慢） |

### 16.8 Software Engineering

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **拆分 tasks.py** | 🔴 高 | 1123 行拆分为 routes/tasks.py + services/task_runner.py |
| **ReviewerService._check_duplication_consistency 实现** | 🔴 高 | 当前空实现 |
| **AST static analysis** | 🟡 中 | 检查死代码 |
| **Golden test for draft output** | 🟡 中 | `tests/golden/` 存放期望 draft snippet |

### 16.9 Software Testing

| 建议 | 优先级 | 说明 |
|------|--------|------|
| **Mutation testing for graph nodes** | 🟡 中 | 用 `mutmut` 对节点逻辑做 mutation coverage |
| **Contract test for API** | 🟡 中 | FastAPI `TestClient` 覆盖所有 endpoint |
| **Deterministic replay** | 🟡 中 | 基于 `TraceStore` replay 指定 task 的执行路径 |

---

## 附录：分析范围确认

本次分析覆盖了以下目录和文件（按优先级）：

**核心代码**（全部读完）：
- `src/research/graph/`（builder.py, nodes/*.py）
- `src/research/agents/`
- `src/research/services/`
- `src/graph/`（state.py, callbacks.py, instrumentation.py, builder.py）
- `src/tools/`（registry.py, mcp_adapter.py, search_tools.py）
- `src/skills/`（registry.py, orchestrator.py, research_skills.py）
- `src/corpus/`（search/reranker.py, store/chunk_store.py）
- `src/db/`（task_persistence.py）
- `src/api/routes/tasks.py`

**Eval / 测试**（全部读完）：
- `eval/runner.py`, `eval/layers/grounding.py`, `eval/layers/hard_rules.py`
- `tests/` 主要测试文件

**文档**（全部读完）：
- `docs/review_plan.md`（分析框架）
- `docs/current-architecture-and-usage.md`（架构现状）
- `docs/design_version/2026-03-29/`（v2 架构设计）
- `docs/active/prd.md`（需求框架）

**配置**：
- `AGENTS.md`, `README.md`, `.github/workflows/ci.yml`

**未深入**（边际价值低）：
- `frontend/src/components/`（UI 组件，只看 import 结构）
- `src/agent/`（legacy 代码，不在主流程）
- `docs/superpowers/`, `docs/phase/`, `docs/examples/`（历史文档）

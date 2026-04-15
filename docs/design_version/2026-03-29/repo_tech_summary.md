# PaperReader_agent 仓库技术总结

日期：2026-03-30

## 结论先行

这个仓库已经不是单纯的 ReAct demo，而是一个正在从“旧 ReAct Agent”迁移到“自定义 11 节点 StateGraph”的文献报告系统。当前主线能力已经包含：

- 基于 `LangGraph StateGraph` 的固定工作流
- arXiv / PDF 双输入
- 引用解析、可达性检查、claim-evidence 验证
- 降级策略与安全中止
- FastAPI 任务接口、SSE 事件流、React 前端面板
- 基本的 eval / diff / gate 框架

从工程成熟度看，仓库当前最强的是：

- `Workflow Orchestration / StateGraph`
- `Grounding / Claim-Evidence Verification`
- `Pydantic / Schema Design`
- `Degradation / Fallback / Abstention`

当前最弱的四项，我的判断是：

1. `Tool Calling / MCP`
2. `Observability / Trace`
3. `Evaluation / Regression`
4. `RAG`

补充说明：

- `Planning（ReAct / Plan-Execute）` 也偏弱，但因为当前产品目标仍是“单篇论文报告生成”，固定图还能撑住；所以我把它放在四个最差项之外。
- `Structured Output` 已经有基本 JSON 化，但还没有做到“强 schema 约束 + 稳定修复”，属于中下水平，不是最差。

## 仓库现状

### 1. 当前主入口

- `src/graph/builder.py`
  - 定义了 11 节点的主 StateGraph：
  - `input_parse -> ingest_source -> extract_document_text -> normalize_metadata -> retrieve_evidence -> draft_report -> repair_report -> resolve_citations -> verify_claims -> apply_policy -> format_output`
- `src/agent/report.py`
  - 单轮报告生成已经走新图。
  - 只有 `chat_history + agent` 的多轮场景才回退到旧 ReAct 路径。
- `src/api/routes/tasks.py`
  - 后端任务 API 与 SSE 状态流的主入口。
- `frontend/src/App.tsx`
  - 当前前端状态面板入口。

### 2. 一个重要架构判断

仓库现在是“双路径并存”状态：

- 新主线：固定 `StateGraph`
- 遗留路径：`create_react_agent(...)`

这带来两个直接后果：

- 主流程的可控性已经明显提升。
- 但“工具调用能力”和“计划能力”仍然主要停留在旧 ReAct 路径，尚未真正迁移到新图内部。

### 3. 当前验证结果

本次总结过程中我实际跑了测试：

- `pytest -q`
- 结果：`155 passed, 3 warnings`

这说明：

- 单元测试和图节点测试覆盖面已经不低。
- 但大量测试仍以 mock 为主，不能等价视为“线上级别回归闭环已经完成”。

## 按技术点逐项判断

| 技术点 | 评分 | 当前状态 | 关键依据 |
|---|---:|---|---|
| Workflow Orchestration / StateGraph | 4.0/5 | 已经是仓库主线，节点拆分清楚，可测试性好 | `src/graph/builder.py`, `src/graph/state.py`, `tests/graph/` |
| Tool Calling / MCP | 1.0/5 | 旧 ReAct 有工具，现主线图没有统一 Tool Runtime；仓库内也没有 MCP 落地 | `src/agent/react_agent.py`, `src/tools/*.py`, `schemas/tools/tools.schema.json` 仍是占位 |
| RAG | 2.0/5 | 有 ingest / index / hybrid search 骨架，但默认运行物料为空，图里只是轻量接入 | `src/ingest/`, `src/retrieval/search.py`, `src/tools/rag_search.py`, `src/graph/nodes/retrieve_evidence.py` |
| Structured Output | 2.5/5 | 已有 JSON 输出约束和 Pydantic 模型，但仍是 prompt + `json.loads()`，不够硬 | `src/graph/nodes/draft_report.py`, `repair_report.py`, `src/verification/claim_judge.py` |
| Planning（ReAct / Plan-Execute） | 2.0/5 | 新图是静态 plan，旧 ReAct 只在多轮 fallback 存在，没有显式 planner / re-plan | `src/agent/react_agent.py`, `src/agent/report.py` |
| Grounding / Claim-Evidence Verification | 3.5/5 | 结构已经成型：citation resolve、tier、reachability、claim judge、policy | `src/graph/nodes/resolve_citations.py`, `verify_claims.py`, `src/verification/` |
| Evaluation / Regression | 2.0/5 | 有 L1/L2/diff/gate 骨架，但 runner 还没有把整个闭环真正跑通 | `eval/runner.py`, `eval/layers/`, `eval/diff.py`, `eval/gate.py` |
| Observability / Trace | 1.5/5 | SSE 只有基础 node event，`NodeStatus` / trace emitter 基本未真正接线 | `src/graph/callbacks.py`, `src/graph/state.py`, `src/api/routes/tasks.py` |
| Degradation / Fallback / Abstention | 3.5/5 | `limited` / `safe_abort` / `abstained` 都已有明确表达 | `src/graph/builder.py`, `extract_document_text.py`, `normalize_metadata.py`, `apply_policy.py`, `format_output.py` |
| FastAPI / SSE / Async | 3.0/5 | MVP 已成型，但仍是单进程内存态任务模型 | `src/api/app.py`, `src/api/routes/tasks.py`, `frontend/src/hooks/useTaskSSE.ts` |
| Pydantic / Schema Design | 3.5/5 | 领域模型清晰，任务模型清晰，但 API / tool schema 还未完全统一 | `src/models/`, `src/corpus/models.py`, `src/models/task.py` |
| AI-assisted Development / Spec-Review-Validation | 3.0/5 | 文档驱动开发很明显，但存在“设计超前于实现”和旧总结过时的问题 | `docs/specs/2026-03-29-v2-architecture-design.md`, `docs/plans/2026-03-29-v2-implementation.md`, `docs/prd.md`, `project_summary.md`, `review_report.md` |

## 重点观察

### Workflow Orchestration / StateGraph

这是当前仓库最成熟的一层。

优点：

- 图节点拆得足够细，语义清楚。
- `AgentState` 已经引入 typed state。
- `safe_abort` 分支已经存在，不是“无脑继续”。
- 节点级测试覆盖比较完整。

不足：

- 图仍然几乎是线性的。
- 没有并行 retrieval / parallel verification。
- 没有 retry / budget / branch-specific policy。

结论：

- 对“单篇论文报告生成”这个目标，当前编排已经够用。
- 如果产品要往“多论文调研”“多 pass 生成”“交互式追问”走，现图还需要升级。

### Tool Calling / MCP

这层是当前最明显的短板。

现状：

- 工具本身有：`arxiv_paper`, `web_fetch`, `local_fs`, `rag_search`
- 但这些工具真正被 `create_react_agent(...)` 使用的，主要还是旧路径
- 新 StateGraph 里很多节点直接 `import` 函数调用，而不是通过统一 Tool Runtime
- 全仓没有 MCP client / server / adapter 的实际实现
- `schemas/tools/tools.schema.json` 还是占位文件

结论：

- 现在的仓库更像“图工作流 + 局部函数调用”，不是“统一工具编排系统”。
- 如果后面要接外部检索、Browser、代码工具、远端知识源，当前结构会很快变得难维护。

### RAG

RAG 是“骨架已搭，但默认不可用”。

已经有的东西：

- `src/ingest/ingestor.py`：种子入库
- `src/ingest/indexer.py`：FAISS 构建
- `src/retrieval/search.py`：BM25 + vector + RRF
- `src/tools/rag_search.py`：图可调用入口

但当前工作区的默认运行物料很弱：

- `data/metadata/meta.sqlite` 存在
- 我实际查了 `documents` / `chunks` 数量，当前都是 `0`
- `data/indexes/vector/faiss.index` 当前不存在

这意味着：

- 代码层有 RAG 框架
- 但仓库当前状态下，RAG 不是开箱即用能力
- `retrieve_evidence` 最后仍然主要依赖 paper abstract / text 和网页抓取兜底

### Structured Output

这层比 RAG 稍好，但还不够硬。

已有能力：

- 报告、claim、citation、final report 都有 Pydantic model
- prompt 要求 JSON
- 节点会把 JSON 解析回 `DraftReport` / `ClaimSupport`

问题：

- 没有 provider-native structured output
- 没有 schema version
- 没有模型输出的严格重试协议
- 一旦 `draft_report` JSON 解析失败，就会退回到一个很弱的 fallback 文本块

结论：

- 这已经不是纯文本拼接
- 但还没达到“工业级 structured generation”

### Planning（ReAct / Plan-Execute）

这层目前是“遗留 ReAct + 固定图”，还不是显式规划系统。

现状：

- `src/agent/react_agent.py` 还在，说明仓库历史上依赖 ReAct
- `src/agent/report.py` 已把单轮主流程切到 StateGraph
- 新图没有 `planner node`、没有 `re-plan`、没有任务预算拆解

我对它的判断是：

- 对当前单目标任务，静态图是可以接受的
- 但如果目标扩展到多论文检索、多轮问答、分段生成，这层会成为瓶颈

### Grounding / Claim-Evidence Verification

这是仓库的一个亮点。

已经落地的关键点：

- `resolve_citations` 把 citation resolve 和 claim judge 分开
- `source_tier` 与 `reachability` 已存在
- `verify_claims` 支持 claim 对 citation 的 support matrix
- `apply_policy` / `format_output` 已把 grounded / partial / ungrounded / abstained 进一步汇总

不足主要在“精度和运行时策略”：

- citation 内容抓取仍然粗糙
- 还是同步串行
- 没有缓存和批量化

但整体上，这一层已经明显高于 MVP 水位。

### Evaluation / Regression

这是另一个明显短板。

有的东西不少：

- `eval/runner.py`
- `eval/layers/hard_rules.py`
- `eval/layers/grounding.py`
- `eval/diff.py`
- `eval/gate.py`

但真正的问题是“闭环没闭合”：

- runner 主要只跑 L1
- L2 虽然定义了，但没有在主 runner 里形成完整主路径
- 没有把 trace / tokens / artifacts 统一沉淀到每次 run
- `docs/evals.md` 还是占位文本

结论：

- 现在是“有 eval 组件”
- 还不是“可依赖的 regression system”

### Observability / Trace

这是当前最容易被误判为“已经有”的部分。

表面上有：

- SSE
- `NodeEventEmitter`
- `NodeStatus`
- 前端 `ToolLogPanel`

但实际问题非常明显：

- `NodeEventEmitter` 目前基本没真正接进图执行链路
- `NodeStatus` 定义了，但没有被节点系统性更新
- `src/api/routes/tasks.py` 里的 `_run_graph_sync()` 是在 `graph.stream(...)` 产出 chunk 后，才把 `node_start` 和 `node_end` 连续 append 进去
- 这意味着它并没有真实反映“节点正在运行中的时间窗口”
- `ToolLogPanel` 看到的其实主要是 node event，不是真实 tool call trace

结论：

- 当前有“状态面板”
- 但还没有“真实 trace 系统”

### FastAPI / SSE / Async

这是一个合格的 MVP。

优点：

- `/tasks` + `/tasks/{id}` + `/tasks/{id}/events` 链路是通的
- `asyncio.create_task(...)` + `run_in_executor(...)` 的组合也合理
- 前端 `EventSource` 消费比较直接

不足：

- 任务存储是进程内 dict
- 只适合单 worker
- 没有 replay / durable queue
- 前端任务上传 PDF 的路径实际上是 `file.text()`，不是后端 `/report/upload_pdf` 那种真正的二进制 PDF 上传

## 当前最差四项及修改建议

### 1. Tool Calling / MCP

为什么最差：

- 主图没有统一 tool runtime
- 仓库里完全没有 MCP 实际接入
- tool schema 还停留在占位文件

建议：

1. 新增 `src/tools/registry.py`，把本地工具统一成 `ToolSpec + invoke()` 接口，不再让图节点直接 import 业务函数。
2. 新增 `src/tools/mcp_adapter.py`，先做最薄的一层 MCP adapter，把未来的远程工具接入点固定下来。
3. 给每个工具补输入输出 schema，替换掉当前占位的 `schemas/tools/tools.schema.json`。
4. 把 `retrieve_evidence`、`ingest_source`、`resolve_citations` 等节点改成通过 registry 调工具，而不是直接调函数。

### 2. Observability / Trace

为什么最差：

- 现在的 SSE 主要是“节点完成后补发事件”
- 没有真实运行中 trace
- 没有稳定的 tokens / duration / tool_calls 记录

建议：

1. 用统一的 node wrapper 包住每个图节点，在 wrapper 内更新 `NodeStatus.started_at/ended_at/duration_ms/error/warnings`。
2. 把 `src/graph/callbacks.py` 真正接进图执行路径，SSE 和 trace file 共用同一套事件源。
3. 在 `/tasks/{id}` 响应中直接返回 `node_statuses`，不要只返最终 markdown。
4. 把前端 `ToolLogPanel` 从“节点面板”升级成“真实工具调用面板”。

### 3. Evaluation / Regression

为什么最差：

- 现在更像“eval 零件齐了”
- 还不是“每次改图、改 prompt、改模型都能稳定回归”的系统

建议：

1. 扩展 `eval/runner.py`，让它能真正串起 L1 + L2，并输出 `meta.json`、`results.jsonl`、`reports/`、`traces/`。
2. 让 `generate_literature_report()` 可选返回更完整的运行结果，而不只是 markdown，至少包括 `final_report`、`tokens_used`、`warnings`。
3. 把 `eval/diff.py` 和 `eval/gate.py` 接到固定 baseline，对 prompt / graph 变更做回归门禁。
4. 维护一小组真实 gold cases，不要只靠 mock / synthetic case。

### 4. RAG

为什么最差：

- 代码骨架存在，但当前默认运行态几乎没有有效 corpus / chunk / index
- `rag_search` 返回的是字符串，不是稳定结构化检索结果
- `retrieve_evidence` 对检索结果的利用仍然很浅

建议：

1. 让 `rag_search` 直接返回结构化 `list[RagResult]`，不要先格式化成字符串再让上游拆。
2. 给仓库加一个最小可运行样本语料或 fixture，确保新环境下 RAG 不是空壳。
3. 增加 query planning / rerank / dedup，而不是只用 abstract 或文首文本做单次查询。
4. 把 RAG 命中率、top-k 来源、空检索率接进 eval 与 trace。

## 紧贴底部但未列入最差四项

### Planning（ReAct / Plan-Execute）

建议方向：

1. 如果后面要做多论文调研，引入显式 `planner` 节点，而不是继续把所有策略硬编码在固定 DAG 里。
2. 把“检索计划”和“写作计划”拆开，例如先产出 section plan，再分节执行。
3. 支持简单 re-plan，例如当 citation resolution 全失败时，回退到二次检索节点。

### Structured Output

建议方向：

1. 优先换成 provider-native structured output 或严格的 Pydantic schema binding。
2. 给输出加 `schema_version`。
3. 把 repair 从“自由 JSON 修复”收束成“typed delta patch”。

## 对 AI-assisted Development / Spec-Review-Validation 的判断

这一项不是弱，而是“文档明显领先于代码”。

优点：

- 有 v2 architecture spec
- 有 implementation plan
- 有 v3 draft PRD
- 有 development log

问题：

- `project_summary.md` 和 `review_report.md` 已经过时，里面还引用了旧文件和旧结论
- `docs/evals.md` 与实际 `eval/` 代码不一致
- 文档之间存在“前瞻性很强，但落地完成度不一致”的情况

建议：

1. 把“文档状态”本身纳入发布检查，例如给 spec / prd / summary 标上 `Draft / Active / Stale`。
2. 每次大版本迁移后，删除或归档过时总结，避免误导后续开发。
3. 让 eval gate 同时校验实现和 spec 中承诺的关键能力是否真的存在。

## 最后判断

如果把这个仓库看成“面向单篇论文报告的 agent 平台 v2”，它已经具备比较清晰的中枢骨架，特别是：

- 图编排
- claim-evidence 验证
- 降级策略
- 前后端任务链路

但如果把它看成“可持续扩展、可稳定回归、可接更多外部能力的 agent 工程底座”，当前真正拖后腿的是：

- 统一工具运行时缺失
- 真实 trace 缺失
- 回归闭环不完整
- RAG 仍偏空壳

所以我的总体结论是：

- 这个仓库已经越过了“脚本式 MVP”的阶段。
- 但还没有进入“稳定 agent platform”的阶段。
- 下一轮最该补的不是继续加新 feature，而是先补齐 `Tool Runtime -> Trace -> Eval -> RAG` 这四条基础设施链路。

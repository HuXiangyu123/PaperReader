# PaperReader Agent — 50 道项目面试问题

> 本报告基于 `project_full_analysis_report.md` 的深度分析，输出 50 道面向 AI Agent 岗位的技术面试问题。
> 项目在简历中使用如下结构展示：
> - **技术栈**：Python 3.10+ / FastAPI / LangGraph / LangChain Core / DeepSeek / PostgreSQL / React 19 / TypeScript
> - **项目简介**：面向科研场景的多阶段 LLM Agent 系统，输入研究主题，自动完成需求澄清→多源检索→结构化抽取→综述生成→引用验证→报告持久化，输出带可追溯引用的结构化 Markdown 综述报告。
> - **核心工作**：多阶段 StateGraph 工作流设计、三源并行检索架构、三层引用验证闭环、前端可视化与 SSE 实时推送

---

## Step A：AI Agent 项目优秀写法模式总结

在 AI Agent 项目中，优秀的简历表达通常遵循以下模式：

1. **业务背景具体化**：不写"做了一个文献综述 agent"，而写"针对研究生综述写作场景，设计了从模糊研究主题到结构化报告的全链路自动化系统"
2. **技术挑战量化**：不写"用了 LangGraph"，而写"用 LangGraph 实现 7 节点 StateGraph，conditional edges 支持 4 种 degradation mode"
3. **核心亮点突出**：最值得强调的是工程实现细节（引用验证闭环、检索 pipeline、评测体系），而非功能描述
4. **评测闭环意识**：不写"做了测试"，而写"设计了 Layer 1 hard rules + Layer 2 LLM grounding judge + Layer 3 human review 三层评测体系，定义了 release gate"
5. **可追溯引用**：引用验证是最能体现 AI Agent 工程能力的地方，需要具体描述（source tier A/B/C/D、claim-level grounding）

---

## Step B：50 道项目问题

### 一、项目定位与业务背景（5 题）

**Q1. 你这个 PaperReader Agent 解决的是什么具体问题？用户是谁？**

考察点：业务理解。不要只说"生成文献综述"，要能说清楚用户痛点（综述写作耗时、引用可靠性差）和具体场景（研究生写论文、做调研）。

---

**Q2. 为什么这个任务不能用一个 LLM 调用完成，非要做成多阶段工作流？**

考察点：架构判断力。核心原因是：需求澄清（clarify）需要追问子问题；检索（search）需要多源并行；抽取（extract）需要逐篇结构化；引用验证（review）需要额外的 grounding 步骤。每个阶段有不同的输入/输出/质量标准，不适合用一个 prompt 完成。

---

**Q3. 你的系统和普通的 RAG 系统有什么本质区别？**

考察点：架构对比。普通 RAG 是"输入 query → 检索 → 生成"，本项目是"模糊主题 → clarify（澄清需求）→ search_plan（规划检索）→ search（多源检索）→ extract（结构化抽取）→ draft（综合生成）→ review（引用验证）"。关键区别在于：多阶段、引用验证闭环、结构化输出。

---

**Q4. 你说的"带可追溯引用的结构化 Markdown 报告"具体指什么？每一步是怎么保证可追溯的？**

考察点：引用验证闭环。需要说清楚三层机制：① resolve_citations 做 URL 可达性检查 + source tier 分类；② verify_claims 做 claim-level evidence 验证；③ apply_policy 在报告中插入 ⚠️ / ⚡ 标记。

---

**Q5. 如果用户输入的主题太宽泛（比如"调研 AI"），你的系统怎么处理？**

考察点：边界处理 + clarify 机制。ClarifyAgent 会生成 `needs_followup=True`，前端追问用户子问题/时间范围。同时 `degradation_mode` 会降级到 `limited` 模式。**注意**：当前系统没有真正的交互式追问，ClarifyAgent 的 `needs_followup` 路径目前直接 END。

---

### 二、Workflow / 架构（8 题）

**Q6. 你说用了 LangGraph，能说说你为什么选 LangGraph 而不是自己写一个 orchestrator 吗？**

考察点：框架选型能力。LangGraph 的核心价值：① StateGraph 支持 TypedDict 强类型状态；② conditional_edges 支持条件路由；③ compile() 返回可测试的 CompiledGraph；④ 内置 checkpointing 支持（未启用但 API 在）；⑤ 社区活跃、文档完整。自己写 orchestrator 的问题是：状态管理、路由逻辑、异常处理都要自己实现，容易出 bug。

---

**Q7. 你的 Research Graph 有 7 个节点，Report Graph 有 11 个节点，这两个图分别用在什么场景？它们之间是什么关系？**

考察点：双图架构理解。Research Graph（7 节点）处理 research 模式：输入研究主题，输出结构化综述。Report Graph（11 节点）处理单篇模式：输入 arXiv URL/ID 或 PDF，输出单篇论文报告。两者共享 `AgentState` 定义、`instrument_node` 包装、`NodeEventEmitter` 事件发射。Research Graph 是 Report Graph 的能力扩展。

---

**Q8. 你的 Graph 拓扑是预定义的，这和真正的 Agent 有什么区别？你认为你的系统是 Workflow 还是 Agent？**

考察点：Anthropic 的 Workflow vs Agent 分类。预定义 Graph 拓扑 = Workflow（适合明确任务）；LLM 动态决定下一步 = Agent（适合开放任务）。**当前判断**：更接近 "Workflow + Tool Calling"，但比纯 Workflow 有 Agentic 特征（节点内部有 LLM 决策、degradation mode 降级）。参考 Anthropic 的分类，属于 **Prompt Chaining + Evaluator-Optimizer 混合模式**。

---

**Q9. 你的 conditional_edges 路由策略具体是怎么设计的？能举个例子吗？**

考察点：路由设计。核心路由：clarify → (needs_followup=True → END | else → search_plan)；search → extract → draft → review → (review_passed=True → persist | else → END)。degradation_mode 是节点返回的状态降级标志，不是 conditional edge 的一部分。

---

**Q10. 你的 degradation_mode 有哪三种状态？分别在什么情况下触发？**

考察点：降级策略设计。`normal` → 节点正常完成；`limited` → 节点部分失败但下游仍可产出有用结果（如 extract_document_text 失败但 metadata.abstract 存在）；`safe_abort` → 关键数据缺失（如 metadata 和 text 都缺失），跳过剩余节点，format_output 发出最小错误摘要而非假报告。

---

**Q11. 如果某个节点失败了，你的系统怎么恢复？有没有重试机制？**

考察点：容错设计。**当前**：节点失败 → 抛出异常 → `instrument_node` 捕获 → 标记 `status=failed` → 后续节点不执行 → 最终状态 `safe_abort`。**没有重试**。这和"re-plan"是两个概念，re-plan 是指当前阶段失败后用不同的策略重新执行，而不是简单重试。

---

**Q12. 你的 7 个节点是串行执行的，有没有可能改成并行？如果并行会带来什么问题？**

考察点：并行化分析。**可以并行的部分**：search_node 内，SearXNG/arxiv API/DeepXiv 已经并行（ThreadPoolExecutor）；extract_node 内，多个 paper card 抽取已经批并行（3篇/批）。**不能并行的部分**：节点间有数据依赖（clarify → search_plan → search → extract → draft → review → persist），每步的输出是下一步的输入。**DAG 级别并行**（如多个 paper card 并行 extract → fan-out）：LangGraph 支持 Send API，但当前未实现。

---

**Q13. 你怎么理解"Supervisor"在 multi-agent 系统中的角色？你的 Supervisor 实现了吗？**

考察点：Multi-Agent 架构理解。Supervisor 的核心职责：基于 LLM 动态决定任务分配、监控进度、处理异常、决定何时终止。当前 `src/research/agents/supervisor.py` 存在但**未在 Graph 中作为节点使用**。实际的 orchestrator 是 `tasks.py` 中的 `_run_graph_sync_wrapper`，是**代码硬编码**的条件路由，不是 LLM 驱动的动态 Supervisor。

---

**Q14. 你的项目里有哪些地方借鉴了 Anthropic 或 OpenAI 关于 Agent 的设计理念？能具体说一个吗？**

考察点：工程视野 + 引用能力。可以提：
- Anthropic 的 ACI（Agent-Computer Interface）理念：tool 定义要有清晰的 description / example usage / edge cases / poka-yoke（防错设计）→ 本项目的 `ToolSpec` 和 `ToolRuntime` 设计参考了这一点
- Anthropic 的 Evaluator-Optimizer 模式：draft（生成）→ review（评审）→ iterate → final → 本项目的 draft_node + review_node + 未来的 revise_node
- Anthropic 的 Parallelization 模式：独立子任务并行 → 本项目 search_node 内三源并行

---

### 三、Agent 设计（7 题）

**Q15. ClarifyAgent 是怎么工作的？它输出什么？**

考察点：Planner 设计。ClarifyAgent 接收用户模糊的研究主题，通过 LLM 生成 `ResearchBrief`：topic（具体化主题）、goal（调研目标）、sub_questions（3-7 个子问题）、desired_output（survey / comparison / related_work）、inclusion_criteria（包含标准）、exclusion_criteria（排除标准）、time_range（时间范围）、ambiguities（未澄清的问题）、needs_followup（是否需要追问）。

---

**Q16. ClarifyAgent 生成的 ResearchBrief 里的 needs_followup 是什么意思？它触发了什么行为？**

考察点：交互式澄清。`needs_followup=True` 表示主题过于宽泛或存在关键歧义，需要人工追问。当前路由：clarify → `needs_followup=True` → END（工作流终止）。**注意**：前端没有实现真正的交互式追问流程，用户会收到"needs_followup"的结果，但没有主动追问 UI。

---

**Q17. SearchPlanAgent 和 SearchPlanPolicy 是什么关系？你有几个不同的 SearchPlan 生成策略？**

考察点：Planner 实现。SearchPlanPolicy 是 **heuristic 策略**（基于规则，不用 LLM）：当查询词是单一关键词时使用策略性规划。SearchPlanAgent 是 **Agent 策略**（用 LLM）：当主题复杂或需要多维度覆盖时使用 LLM 生成查询计划。

---

**Q18. review_node 和 ReviewerService 是什么关系？review_node 为什么内部调用了 ground_draft_report？**

考察点：Service 解耦。review_node 是 Graph 节点（返回值写回 state）。ReviewerService 是纯业务逻辑（生成 ReviewFeedback，不涉及 Graph 交互）。`ground_draft_report` 是 bridging function，串联 legacy report graph 的三个节点（resolve_citations → verify_claims → format_output）来产生 verified_report。review_node 调用它的原因是：Graph 层面的 review 需要先做引用验证，再做质量检查。

---

**Q19. 你的 claim-level grounding 具体是怎么做的？claim 和 citation 是什么关系？**

考察点：引用验证深度理解。每个 Claim 可能引用多个 Citation（`citation_labels: list[str]`），每个 (Claim, Citation) 配对产生一个 `ClaimSupport`（support_status ∈ {supported, partial, unsupported, unverifiable}）。Claim 的 `overall_status` 从其 supports 推导：任何 supported → grounded；最好的是 partial → partial；全部 unsupported/unverifiable → ungrounded。

---

**Q20. Source Tier 的 A/B/C/D 是怎么分的？为什么 GitHub 是 C 而不是 A？**

考察点：引用权威度设计。Tier A：论文本身/DOI/正式出版商/ OpenReview/arXiv paper page（权威学术来源）。Tier B：官方文档/官方 benchmark/model cards（官方技术来源）。Tier C：GitHub repos/Colab（代码实现来源，非学术权威）。Tier D：博客/论坛/Wiki（社区来源）。**设计原则**：GitHub 是代码可用性的信号，但不是学术权威，和 arXiv/DOI 不是同一级别的 trust signal。

---

**Q21. 如果 verify_claims 发现 50% 的 claim 都是 ungrounded，你的系统怎么处理？**

考察点：Policy 引擎设计。根据 `apply_policy` 规则：grounded ≥ 80% → report_confidence = high；50-79% → limited；< 50% → low（只输出最小安全摘要，full report 被抑制）。同时 ungrounded claim 会在报告中标记 `「⚠️ 未找到充分证据支撑」`，partial claim 标记 `「⚡ 部分证据支撑，需进一步核实」`。

---

### 四、Context Engineering（5 题）

**Q22. 你的 draft_node 里有一个 200 行的 system prompt，内联在 Python 文件里。这种做法有什么问题？**

考察点：Prompt 工程最佳实践。问题：① 无版本控制（git diff 看不到变更）；② 无 prompt A/B test 能力；③ 难以在 eval 中对齐 prompt version；④ 违反单一职责（prompt 是数据，不是代码）。**建议**：抽取到 `src/research/prompts/draft_system_prompt.py`，与 commit hash 关联。

---

**Q23. 当你从 50 篇 paper cards 生成综述时，context window 不够用怎么办？**

考察点：Context 压缩。当前 `draft_node` 的做法：① `cards[:30]` 直接截断（简单粗暴）；② LLM max_tokens=8192 硬限制；③ 没有摘要压缩或分层策略。**问题**：会导致后 20 篇论文被忽略，taxonomy 覆盖不完整。

---

**Q24. 你的 RAG 检索用了三路（ SearXNG + arXiv API + DeepXiv），它们各自的优势是什么？你怎么做去重的？**

考察点：多源检索设计。SearXNG：广度召回，支持多引擎（arxiv/Google Scholar），但 metadata 质量一般。arXiv API：metadata 最完整（title/authors/abstract/year），但依赖 DOI/ID 精确匹配。DeepXiv：提供 TLDR + keywords，擅长发现 trending papers 和 SearXNG 遗漏的相关论文。去重优先级：arXiv API > DeepXiv > SearXNG（基于 arxiv_id + url 精确匹配）。

---

**Q25. CrossEncoderReranker 你实现了吗？为什么 search_node 里没有调用它？**

考察点：实现完整性陷阱（这个问题是陷阱）。CrossEncoderReranker 在 `src/corpus/search/reranker.py` 中完整实现（模型加载、pair 构建、RRF 融合），但 `search_node` 的最终排序**没有调用 reranker**，候选论文按 dedup 顺序直接返回。这意味着 reranker 是"技术储备"而非"生产代码"。

---

**Q26. 你的 ChunkStore 写入了论文 abstract，但后续检索没有用到这些 chunks，这是为什么？**

考察点：系统实现完整性。`_ingest_paper_candidates` 将 top-50 论文的 abstract 作为 CoarseChunk 写入 PostgreSQL，但 `rag_search` 实际上搜的是 SearXNG/arxiv API 返回的 metadata，没有从本地 chunks 检索。**原因**：Phase 2 的重点是让检索pipeline跑通，vector retrieval 留到 Phase 4。

---

**Q27. 你的 Memory 层是怎么设计的？Episodic Memory 和 Semantic Memory 分别存在哪里？**

考察点：Memory 设计。Episodic Memory（任务级会话历史）：`TaskRecord.chat_history`（PostgreSQL 持久化）+ `task.node_events`（内存）。Semantic Memory（结构化知识）：`ChunkStore`（PostgreSQL coarse/fine chunks）。`.memory/` 目录（semantic + episodic JSON files）存在但**不参与主流程**。

---

### 五、Multi-Agent（4 题）

**Q28. 你的系统里有 ClarifyAgent、SearchPlanAgent、ReviewerAgent，但它们是真正的多 Agent 系统吗？它们之间怎么通信的？**

考察点：Multi-Agent 真实性判断。**不是**真正的 Multi-Agent。理由：① 这些"Agent"本质是 graph node 里的 LLM 调用，不是独立进程/线程；② agent 间通过 `AgentState` dict 通信，不是 agent 间消息传递；③ 节点间串行执行，不是并行协商；④ 没有 agent 级别的超时/重试/降级。**更像**：Agent-Enhanced Workflow（每个节点背后有 LLM，但决策空间受节点边界限制）。

---

**Q29. 你说 RetrieverAgent、PlannerAgent、AnalystAgent 这些 agent 文件存在但没被使用，这是为什么？**

考察点：设计过度 vs 渐进实现。这些 agent 文件定义了 system prompt 和基本结构，但实际执行路径走的是对应的 graph node 函数（如 `search_node`、`clarify_node`）。**可能原因**：Phase 1-3 优先让 graph 跑通，agent 升级是 Phase 4 的目标。当前设计是"渐进增强"路径，graph nodes 是 MVP，agent 化是未来方向。

---

**Q30. 如果让你把这些 Agent 升级成真正可以并行工作的多 Agent 系统，你会怎么设计 agent 间的通信？**

考察点：Multi-Agent 架构设计。建议：① 每个 agent 是独立可运行的 LLM 调用（有 system prompt + tool set）；② agent 间通过共享的 **workspace 状态**（而非函数调用）通信；③ Supervisor 基于 LLM 动态分配任务（而非代码 if/else）；④ 需要消息队列或事件总线（而非直接调用）。参考 CrewAI / LangGraph 的 subgraphs 模式。

---

### 六、Tools / Function Calling（5 题）

**Q31. 你的 ToolRuntime 注册了很多工具，但 graph 节点里很多工具是直接 import 调用的，没有走 ToolRuntime.invoke()。这样做有什么问题？**

考察点：工具层架构一致性。问题：① 工具调用无统一 trace（`instrument_node` 追踪节点，不追踪节点内的函数调用）；② 重试/降级逻辑散落各处；③ tool registry 的价值被浪费（注册了但没调用）；④ 未来想统一加 middleware（限流/鉴权）会很困难。

---

**Q32. 你的工具调用的超时是怎么控制的？draft_node 的 LLM 调用有 240s timeout，其他节点呢？**

考察点：容错设计细节。`build_reason_llm(..., timeout_s=240)` 在 `draft_node` 明确设置了 240s timeout。HTTP 请求（SearXNG/arXiv API）有 30s 内部限制。但其他节点（clarify/search_plan/extract）的 LLM 调用**没有显式 timeout**，依赖全局设置。**风险**：如果 LLM 服务 hang，整个任务会无限等待。

---

**Q33. 你的 resolve_citations 节点有没有做 HTTP 请求的重试？网络抖动的时候会发生什么？**

考察点：工具可靠性。当前 `_run_http_with_timeout` 没有重试逻辑，一次 HTTP 失败 → citation 标记 `reachable=False` → claim 可能降级为 ungrounded。**建议**：增加指数退避重试（3 次，间隔 1s/2s/4s），提高 citation resolution rate。

---

**Q34. 你怎么理解"工具定义即 Agent-Computer Interface（ACI）"这个概念？你的 tool 定义做到了吗？**

考察点：Anthropic ACI 理念落地。ACI 核心要求：① 工具定义像写给 junior developer 的文档（清晰 description）；② example usage + edge cases + input format requirements；③ poka-yoke（防错设计，如强制绝对路径而非相对路径）。当前 `ToolSpec` 有 name/description/category/input_schema，但**缺少 example usage / edge cases**。SearXNG tool 的 description 是"通过 SearXNG 搜索"，过于笼统。

---

**Q35. 如果 LLM 生成的 JSON 解析失败了，你的 fallback 机制是什么？fallback 生成的报告质量怎么样？**

考察点：降级策略 + 质量保证。Fallback：`_fallback_draft` 基于 paper cards 的 abstract 手工构造 sections。**质量**：极低——introduction 是"本综述围绕XX，共分析了N篇相关论文"；methods 是"（方法对比待补充）"；taxonomy 是"（分类学待补充）"。**这正是之前用户看到的水报告来源**。根本原因是 LLM 生成 JSON 失败（可能因为网络/模型/超时），fallback 接管后内容质量断崖式下降。

---

### 七、MCP / Skills（4 题）

**Q36. MCP 的 stdio transport 和 HTTP transport 分别适用什么场景？你的 MCPAdapter 两种都支持了，具体怎么选的？**

考察点：MCP 协议理解。Stdio：MCP server 和 Client 在同一台机器，通过 stdin/stdout 通信（`subprocess.Popen`），低延迟，适合本地 server（如 `mcp-server-fetch`）。HTTP：Remote MCP server，通过 HTTP POST 通信，适合云端部署或跨网络调用。本项目两种都支持，`MCPServerConfig` 有 `transport` 字段选择。

---

**Q37. 你的 MCPAdapter 已经完整实现了，但有没有实际注册任何 MCP server？为什么？**

考察点：系统完整性 vs 实际使用。MCPAdapter 的 transport / capability discovery / invoke 逻辑完整，但 `get_skills_registry()` 没有注册任何 MCP server。**原因**：Phase 4 才接真实 MCP server，当前还在设计验证阶段。**风险**：如果没有人推动 Phase 4，这套代码可能永远只是"设计文档"。

---

**Q38. SkillOrchestrator 的 implicit 模式和 explicit 模式分别是什么？你有没有用过 implicit 模式？**

考察点：Skill 路由设计。Explicit：`/skill_id args` → 直接路由到对应 skill 函数。Implicit：用户说"帮我分析这些论文"，LLM 决定使用哪些 skill（`lit_review_scanner → comparison_matrix_builder → writing_scaffold_generator`）。Implicit 模式存在但**未在前端暴露**，`_llm_decide_tools` 的 decision prompt 较简陋（1024 max_tokens）。

---

**Q39. 你的 SkillRegistry 有 4 种 backend handler（LOCAL_GRAPH / LOCAL_FUNCTION / MCP_TOOLCHAIN / MCP_PROMPT），它们分别解决了什么问题？为什么需要这么多种？**

考察点：Skill backend 抽象。LOCAL_GRAPH：skill 映射到 LangGraph 节点（复用已有 graph 能力）。LOCAL_FUNCTION：skill 是独立的 Python 函数（最灵活）。MCP_TOOLCHAIN：通过 MCP 协议调用外部工具生态。MCP_PROMPT：通过 MCP 获取动态生成的 prompt（prompt as a service）。不同 backend 支持不同的 skill 表达粒度和复用场景。

---

### 八、Lifecycle / Harness（4 题）

**Q40. 你的任务 terminate 端点（`POST /tasks/{id}/terminate`）是真正中止了任务还是只是标记了状态？**

考察点：Lifecycle 真实性。当前是**标记式**：设置 `status=FAILED, error="Terminated by user"`，但 `ThreadPoolExecutor` 中的线程继续运行直到自然结束。**原因**：Python 的 threading 不支持强制中止（`Thread.kill()` 不存在）。真正的 termination 需要：① `asyncio.Task.cancel()`；② 使用 multiprocessing 而非 threading；③ 在 LLM 调用层面加可中断检查点。

---

**Q41. 如果后端服务重启了，正在运行的任务会怎么样？你有没有从中断点恢复的能力？**

考察点：状态持久化与恢复。当前：TaskRecord 持久化到 PostgreSQL，但 `graph.stream(initial_state)` **从初始状态重新开始**，不记录当前节点位置。重启后无法从中断点恢复。**原因**：没有 `current_stage` 的 checkpointing + restart-from-stage 逻辑。LangGraph 本身支持 checkpointing（`MemorySaver`），但未启用。

---

**Q42. 你的 instrument_node 是怎么工作的？它解决了什么问题？**

考察点：Harness 设计。`instrument_node` 是一个 wrapper function：对每个 graph node 注入：① 计时（`duration_ms`）；② token 消耗追踪（`tokens_delta`）；③ 节点事件发射（`on_node_start` / `on_node_end`）；④ reasoning 内容捕获（`_reasoning_content`）；⑤ 异常捕获（标记 `status=failed`）。**解决的问题**：节点黑盒 → 节点完全可观测，支持前端可视化、eval trace 生成、慢节点分析。

---

**Q43. SSE 推送是怎么实现的？客户端断开连接后服务端会怎样？**

考察点：实时推送架构。`/tasks/{id}/events` SSE endpoint：服务端 `asyncio.Queue`，每个节点事件 `put_nowait` 到 queue，客户端通过 `EventSource` 消费 stream。**问题**：客户端断开后服务端继续运行（`asyncio.QueueFull` 被静默吞掉），无 event replay（断点续传）。Anthropic 的研究指出这是 MVP 阶段的合理折中。

---

### 九、Eval / Benchmark（5 题）

**Q44. 你的三层 Eval 体系具体是哪三层？Layer 2 为什么不放在 CI 里运行？**

考察点：Eval 体系设计。Layer 1（hard rules）：纯代码断言（结构完整性/引用格式/URL可达性/token预算），不需要 LLM，成本极低，CI 中执行。Layer 2（grounding judge）：LLM-as-judge 评估 claim support rate / citation resolution rate，需要真实 LLM API，CI 中无 `DEEPSEEK_API_KEY` 所以跳过。Layer 3（human review）：人工评分（readability/insight depth/critical omission），需要人工介入。**改进建议**：Layer 2 用 mock LLM 或 replay 日志，在 CI 中执行。

---

**Q45. 你的 claim-evidence gold cases 是什么意思？你怎么保证 ground truth 的质量？**

考察点：Ground truth 标注。Gold cases（共 3 个）：预先标注了 claim 的 `expected_grounding`（grounded/partial/ungrounded）和 `source_excerpt`（原文引用）。**来源**：人工从论文原文中提取，并标注 ground truth。**问题**：只有 3 个 gold cases，覆盖面极窄；且随着系统 prompt 变更，gold cases 可能不再适用（需要定期 re-annotate）。

---

**Q46. 如果 Layer 2 的 claim_support_rate 只有 55%，你的 release gate 会怎么判断？**

考察点：Policy 决策。Layer 2 threshold：claim_support_rate ≥ 80% → pass。但 55% < 80%，**不满足 release gate**。同时 evaluation threshold（`check_claim_support_rate` 的 `threshold=0.6`）是 60%，55% < 60%，也**不满足 evaluation**。如果连续两版都在 55% 附近，说明当前 retrieval 质量或 draft 质量有系统性问题，需要专项优化而非盲目发布。

---

**Q47. 你有没有做过 regression 测试？regression 是怎么判定的？**

考察点：持续改进机制。`eval/diff.py` 计算跨 run 的 pass rate delta。Regression 判定：`layer2_pass_rate_delta < -2%`（相比上一版下降超过 2%）。**但 CI 中不执行 Layer 2**，所以 regression 检测只在手动跑 eval 时触发。**缺失**：没有自动化 regression 告警（Slack/PagerDuty），依赖人工检查 eval/runs/ 目录。

---

**Q48. 你的 retrieval quality 有量化评估吗？recall@K / MRR 这些指标你算了哪个？**

考察点：Retrieval 评测。**当前**：无离线 retrieval benchmark。`tests/corpus/search/` 下是单元测试，不是 retrieval 质量评估。`search_node` 返回多少篇论文、哪些论文被 dedup 了，没有 ground truth 召回率追踪。**建议**：基于 `eval/cases.jsonl` 的 `expected_papers` 字段，计算 recall@20 / MRR@20，作为 retrieval eval 的主要指标。

---

### 十、软件工程（4 题）

**Q49. `src/api/routes/tasks.py` 有 1123 行，你打算怎么拆分它？**

考察点：代码质量与重构。职责拆分方案：① `task_runner.py`：`_run_graph_sync_wrapper` / `_run_graph_sync` / `_schedule_task_run` → 任务执行逻辑；② `task_api.py`：保留所有 `@router` 装饰器 + request/response model；③ `task_service.py`：`TaskRecord` 管理 / `_serialize_task` / `_persist_*` → 持久化逻辑；④ `task_debug.py`：`/llm-test` / `/graph-test` / `/sync-test` 调试端点单独文件。

---

**Q50. ReviewerService 的 `_check_duplication_consistency` 是空实现，这个方法存在但什么都不做，你打算怎么处理？**

考察点：代码质量 + 诚信度。**选择一**：实现它（分析 sections 之间是否有重复论点、claim 是否在多处重复引用同一论文）。**选择二**：删掉它（方法签名存在但无人调用，说明从未被需要）。**选择三**：改成占位注释说明为什么为空（"section-level 重复检测需要跨 section 的文本相似度计算，Phase 4 规划"）。**建议**：先问产品/用户是否需要这个功能，再决定实现还是删除，不要让 dead code 留在代码库里。

---

### 十一、指标提升与优化过程（4 题）

**Q51. 你的 `_inject_citation_content` 函数是一个 workaround，你知道它修复了什么根本问题吗？**

考察点：根因分析能力。`draft_node` 的 system prompt 要求 LLM 生成 citations（含 url/reason），但**没有要求生成 fetched_content**（论文摘要/正文片段）。导致后续 `resolve_citations` 无法从 URL 获取 content 时，claim verification 直接失败。`_inject_citation_content` 是事后打补丁（用 paper_cards 的 abstract 填充 fetched_content）。**根本修复**：修改 draft system prompt，要求 LLM 在生成 Citation 时同时输出 `fetched_content_snippet`（从 paper_card 的 abstract 中提取相关片段）。

---

**Q52. 你的 grounding pipeline 从 legacy report graph 复用到了 research graph，这个桥接是怎么做的？有没有引入耦合问题？**

考察点：Legacy 复用设计。`ground_draft_report` 函数（`src/research/services/grounding.py`）串联 legacy 节点（resolve_citations → verify_claims → format_output）作为 standalone 函数调用，不经过 Graph 的 stream 接口。**好处**：无需改动 legacy graph，research graph 直接复用 grounding 能力。**问题**：状态管理独立（传入 `state` dict，返回结果 patch），不是真正的 Graph 内节点，长期维护两套状态模型有耦合风险。

---

**Q53. 你有没有测量过每个节点的耗时占比？哪个节点最慢？**

考察点：性能分析意识。基于 `NodeEventEmitter` 的 `duration_ms` 数据，预期各节点耗时：`search_node`（最慢，多路 HTTP 请求）> `draft_node`（次慢，LLM 8192 tokens）> `extract_node`（LLM 批量调用）> `resolve_citations`（HTTP URL fetch）> `clarify/search_plan`（较快，结构化输出）> 其他节点（毫秒级）。**优化方向**：search_node 增加并发度；draft_node 减少 token 消耗；extract_node 调大 batch_size。

---

**Q54. 你的项目用 PostgreSQL only，不允许 SQLite，这个硬约束是哪里来的？PostgreSQL 和 SQLite 在你这个场景下分别的优势是什么？**

考察点：数据库选型理解。**硬约束来源**：`AGENTS.md` 明确禁止 SQLite（"Do not introduce SQLite for metadata, task state, report persistence, or test fixtures"）。**理由**：PostgreSQL 支持 JSONB（task snapshot 灵活存储）、pgvector（future vector retrieval）、ACID 事务（任务持久化可靠性）、连接池（多并发任务）。**SQLite 优势**（本项目不需要）：零配置、嵌入式、适合单进程低并发。**实际**：当前 pgvector 未启用，PostgreSQL 主要用 JSONB 和事务。

---

## 附录：问题难度分布

| 难度 | 题号 | 说明 |
|------|------|------|
| **基础** | Q1-5, Q15-16, Q22, Q41-43, Q49-50 | 考察项目基本理解和代码诚信 |
| **进阶** | Q6-14, Q17-21, Q23-28, Q31-35, Q36-39, Q44-48 | 考察架构设计能力和工程判断 |
| **深度** | Q29-30, Q40, Q51-54 | 考察 multi-agent 系统理解、根因分析、性能优化 |
| **陷阱** | Q25, Q35, Q50 | 暴露实现完整性的真实问题 |

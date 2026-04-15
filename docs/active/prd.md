# 需求、推荐文件框架路径


```typst
src/
  api/
    routes/
      tasks.py
      uploads.py
      workspaces.py
      corpus.py
      research.py
      evals.py
  research/
    graph/
      builder.py
      state.py
      nodes/
        clarify.py
        plan_search.py
        search_corpus.py
        select_papers.py
        extract_cards.py
        synthesize.py
        review.py
        revise.py
        write_report.py
    services/
      orchestrator.py
      planner.py
      synthesizer.py
      reviewer.py
  corpus/
    ingest/
    search/
    store/
  tools/
    registry.py
    runtime.py
    specs.py
    mcp_adapter.py
    providers/
  models/
  tasking/
  eval/
    runner.py
    cases/
    gates/
frontend/
```


可以收敛成这条主线：

**输入研究任务 → 澄清需求 → 规划检索 → 获取论文 → 抽取结构化 paper card → 跨论文整合 → reviewer 审查 → 生成/修订综述报告 → 持久化到 workspace**

所以系统边界应该这样定：

- **输入**：topic / query / arXiv id / DOI / PDF / 本地目录
- **输出**：research brief、query plan、candidate papers、paper cards、comparison matrix、review log、report draft、final report
- **系统特征**：长流程、可中断、可恢复、可追踪、可复用

这和你现在 demo 的能力是连续的：当前已经有 `StateGraph`、任务 API、SSE、claim-evidence 验证、Pydantic 模型、降级策略；缺的是让这些能力从“单篇报告图”升级成“多产物 research workflow”。

---

# 模块拆分

### 1. Research Orchestrator 模块

这是整个系统的中枢，不是业务逻辑本身，而是任务编排器。

它负责：

- 启动一个 research task
- 维护 `ResearchState`
- 驱动阶段切换：clarify → plan → search → read → synthesize → review → write
- 失败重试、降级、中止
- 把中间产物写入 workspace

你现在 demo 里最成熟的就是这一层，因为已有 11 节点 `StateGraph`、typed state、safe\_abort 分支和节点级测试。
所以这里不要重写范式，而是把当前“单篇论文报告图”升级成“研究工作流图”。重点不是更多自由规划，而是**先让显式阶段和中间产物落地**。

建议新增：

- `src/research/graph/builder.py`
- `src/research/graph/state.py`
- `src/research/graph/nodes/clarify.py`
- `src/research/graph/nodes/plan_search.py`
- `src/research/graph/nodes/search_corpus.py`
- `src/research/graph/nodes/extract_cards.py`
- `src/research/graph/nodes/synthesize_matrix.py`
- `src/research/graph/nodes/review_report.py`
- `src/research/graph/nodes/write_final.py`

---

### 2. Clarifier / Planner 模块

这对应你简历里的 “Scope → Search”。

它负责：

- 把用户模糊 query 变成结构化 `ResearchBrief`
- 拆分子问题
- 生成 query plan
- 给出 inclusion / exclusion criteria
- 指定输出格式（综述、对比表、related work、paper reading notes）

当前 demo 的短板之一就是 planning 仍然偏弱：新图是静态 plan，旧 ReAct 只在 fallback 存在，没有显式 planner / re-plan。
所以这个模块要新做，而且它应该是**第一个新增节点**，不是等到最后才补。

建议领域对象：

- `ResearchBrief`
- `SubQuestion`
- `SearchPlan`
- `SearchQuery`
- `SectionPlan`

---

### 3. Corpus / Retrieval / RAG 模块

这对应你简历里的 “论文获取、本地论文库、连续研究记忆”。

它负责：

- 在线检索：arXiv / Crossref / Semantic Scholar（后续）
- 本地文件读取
- PDF ingest、chunk、index
- keyword + vector + hybrid search
- rerank / dedup
- 结构化返回候选论文，而不是字符串拼接

你当前 demo 的 RAG 评价只有 2/5，原因不是“没写代码”，而是默认 corpus 几乎为空、`rag_search` 返回字符串、`retrieve_evidence` 对检索结果利用很浅。
所以这个模块不是“补一个向量库”就完了，而是要做成真正的 **Corpus Service**。

建议拆成 3 层：

- `src/corpus/ingest/`
- `src/corpus/search/`
- `src/corpus/store/`

核心对象：

- `Document`
- `Chunk`
- `PaperCandidate`
- `RagResult`

---

### 4. Paper Reader / Structured Extraction 模块

这对应你简历里的 “单篇抽取、Paper Card”。

它负责：

- 抽取标题、作者、年份、venue、abstract
- 抽取问题、方法、数据集、指标、贡献、局限
- 生成 `PaperCard`
- 保存 citation anchors / evidence spans

当前 demo 在 structured output 上已经有基础：Pydantic model、JSON 输出约束、repair 节点都有，但还不够硬，缺 provider-native structured output、schema version、严格重试协议。
所以这个模块不要再走“自由文本→硬 parse”的老路，要从一开始就强 schema 化。

建议对象：

- `PaperMetadata`
- `PaperCard`
- `PaperMethodSummary`
- `EvidenceSpan`

---

### 5. Synthesizer / Writer 模块

这对应你简历里的 “跨文献对比、综述生成”。

它负责：

- 聚合多个 `PaperCard`
- 自动生成 taxonomy
- 生成 comparison matrix
- 生成 section outline
- 生成 survey draft / related work draft

这个模块不是把几篇摘要拼起来，而是要面向中间产物：

- `ComparisonMatrix`
- `TaxonomyTree`
- `ReportOutline`
- `ReportDraft`

这一步最好不要直接输出最终报告，而是先产出**中间结构**，让 reviewer 能审查。

---

### 6. Reviewer / Grounding / Verification 模块

这对应你简历里的 “审查修订、引用可靠性”。

你当前 demo 的亮点恰恰就在这里：已有 citation resolve、source tier、reachability、claim judge、policy 汇总，这说明 reviewer 不是凭空新造，而是可以直接继承。
所以这个模块应继续沿用 demo 里的强项，变成 research workflow 中的核心阶段。

它负责：

- 检查 coverage gap
- 检查 unsupported claims
- 检查 citation reachability
- 检查结构重复
- 生成 `ReviewFeedback`
- 必要时驱动二轮检索

建议对象：

- `ReviewFeedback`
- `CoverageGap`
- `ClaimSupport`
- `RevisionAction`

---

### 7. Tool Runtime / MCP / Skills 模块

这块你简历里已经写了，但当前 demo 实际最弱。

repo 总结里讲得很清楚：当前工具本身有 `arxiv_paper`、`web_fetch`、`local_fs`、`rag_search`，但主要还是旧 ReAct 在用；新图节点很多是直接 import 函数；没有 MCP adapter；tool schema 还只是占位。
所以这层必须先补，不然你后面所有“skills / MCP / multi-agent”都会变成简历语言，不是工程能力。

---


# 计划 phase

### Phase 1：把底座从“单篇报告图”升级成“research task”

要做：

- `ResearchTask` / `Workspace` / `Artifact` schema
- `/research/tasks` + `/tasks/{id}` + `/events`
- 真正二进制 PDF 上传
- `clarify` / `search_plan` / `paper_card` 三个核心节点
- 工具 registry 雏形

### Phase 2：把 RAG 和 corpus 做成真能力

要做：

- ingest / chunk / index
- structured `RagResult`
- local folder / uploaded PDF / online source 统一入库
- candidate papers + dedup + rerank

### Phase 3：把 reviewer 和 trace 做起来

要做：

- `ReviewFeedback`
- node wrapper + tool trace
- workspace artifact 面板
- `/internal/evals/run`

### Phase 4：最后才做更强的 multi-agent 和 MCP

要做：

- `mcp_adapter.py`
- planner / retriever / analyst / reviewer 多角色拆分
- re-plan

这条顺序和 repo 总结的结论一致：下一轮最该补的不是加新 feature，而是先补齐 `Tool Runtime -> Trace -> Eval -> RAG` 这四条基础设施链路。
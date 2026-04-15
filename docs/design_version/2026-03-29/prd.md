# PRD: Literature Report Agent v3 — 报告质量 & 多论文检索 & R1 兼容 & 追问对话

| 字段 | 值 |
|------|----|
| **版本** | v3.0-draft |
| **日期** | 2026-03-29 |
| **状态** | Draft — 待评审 |
| **前置文档** | `docs/specs/2026-03-29-v2-architecture-design.md`（v2 StateGraph 设计）<br>`docs/plans/2026-03-29-v2-implementation.md`（v2 实施计划）<br>`report_ref.md`（目标质量参照） |

---

## 1. 背景与动机

### 1.1 现状

v2 已将系统从 `create_react_agent` 黑盒迁移到 11 节点 StateGraph，实现了：

- arXiv / PDF 对称摄入
- 引用可达性 & Tier 分级
- Claim-Evidence 验证 + 降级策略
- React 前端实时 DAG 可视化

### 1.2 核心问题

在 v2 交付物上实际运行「Attention Is All You Need」(1706.03762) 后，暴露出四个主要差距：

| # | 问题 | 现状根因 |
|---|------|----------|
| P0 | **DeepSeek R1 不兼容** | `ChatOpenAI` 不提取 `reasoning_content`；方舟 / DeepSeek 官方 R1 推理 token 被丢弃 |
| P1 | **仅单论文自引用** | `retrieve_evidence` 只做 RAG + Google Scholar HTML 抓取，无 arXiv/Semantic Scholar 多论文检索 |
| P2 | **报告内容过少、不可追问** | System prompt 要求 6 个 JSON 短字段；前端只展示静态 Markdown，无对话 |
| P3 | **思考过程不可见** | SSE 仅有 `node_start`/`node_end`，用户不知道模型是否做了多步推理 |

### 1.3 目标质量参照

`report_ref.md`（~415 行）展示了一份合格的论文精读报告应有的深度：

- 6 大章节 × 多级子节（I-VI）
- 相关工作 / 实验结果用 Markdown 表格
- 关键公式（LaTeX）+ 符号表 + 直觉解释
- 代码级实现分析
- 以严肃 reviewer 视角的 novelty 评级与 failure case 分析
- 全文事实声明附引用链接

---

## 2. 目标与非目标

### 2.1 目标（按优先级）

| 优先级 | 目标 | 成功标准 |
|--------|------|----------|
| **P0** | 报告质量达到 `report_ref.md` 水准 | 对同论文生成报告 ≥ 300 行，包含表格、公式、代码、批判分析 |
| **P0** | 兼容 DeepSeek R1 / 方舟 / OpenAI 多后端 | R1 推理 token 可提取并流式展示；非 R1 模型正常工作 |
| **P1** | 多论文综合文献调研 | 自动检索 ≥ 5 篇相关论文，构建对比表格，引用含外部 URL |
| **P1** | 前端多轮追问 | 用户在报告页可追问 ≥ 3 轮，AI 基于报告 + 论文上下文回答 |
| **P2** | 思考过程可视化 | 前端实时展示 LLM 推理 trace（R1 `<think>` 或中间输出） |

### 2.2 非目标（v3 不做）

- 跨论文综述合成（仅检索并对比，不做真正的 survey synthesis）
- 多租户 / 用户认证
- Docker / 云端部署
- PDF 图表 / 公式 OCR 抽取（依赖纯文本层）
- Prompt injection 防护
- 火山方舟 `responses.create` + `web_search` tool（本项目走 Chat Completions，不接 Responses API）

---

## 3. 用户故事

### US-1 深度论文精读

> 作为一名研究者，我输入一个 arXiv ID，系统自动生成一份含公式、表格、代码分析、批判评价的完整中文精读报告（~300+ 行 Markdown），包括相关工作对比和 failure case 分析，使我能快速把握论文核心并评估其 novelty。

### US-2 多论文关联

> 在精读报告的「背景与相关工作」一节中，系统自动检索该论文的前驱工作和后续引用，以 Markdown 表格呈现至少 5 篇相关论文的年份、方法、与本文关系，引用 URL 可直接点击。

### US-3 报告追问

> 报告生成后，我在前端页面提出补充问题（如「请展开分析 positional encoding 的局限性」），AI 基于已生成报告和论文原文回答，支持多轮。

### US-4 推理过程透明

> 在报告生成过程中，我能在前端看到模型正在思考的内容（R1 模型的推理 token），而不只是节点开始/结束。

### US-5 模型灵活切换

> 我可以通过 `.env` 中的 `LLM_PROVIDER` 和模型名，在 DeepSeek 官方（含 R1）、方舟、OpenAI 之间自由切换，无需改代码。

---

## 4. 功能需求

### FR-1 多 Pass 报告生成

| 项 | 说明 |
|----|------|
| **Pass 1: 大纲 + Claims + Citations** | 输入完整论文文本（≤ 32K chars）+ 相关论文元数据 + evidence。输出 JSON：6 节大纲摘要、结构化 claims、citations。 |
| **Pass 2: 逐节展开** | 对每个大节单独调用 LLM，输入大纲 + 对应论文段落 + evidence。输出该节的富 Markdown（含表格、公式、代码块、分析）。 |
| **Assembly** | 合并为 `DraftReport`，进入现有 repair → resolve → verify → policy → format 流程。 |

### FR-2 System Prompt 体系

新建 `src/agent/prompts_v2.py`，包含：

- `REPORT_ROLE_PREAMBLE`：角色声明（「资深学术审稿人 + 论文精读助手」），适用全部 prompt。
- `OUTLINE_SYSTEM_PROMPT`：Pass 1 用。输出 JSON schema。
- `SECTION_EXPAND_PROMPT`：Pass 2 用。逐节指令，含质量要求（表格、LaTeX、code、批判）。
- `CHAT_SYSTEM_PROMPT`：追问对话用。含报告摘要 + 论文上下文。

详细 prompt 文本见附录 A。

### FR-3 多论文检索节点

新增图节点 `search_related_papers`，插入 `normalize_metadata` → `retrieve_evidence` 之间。

| 数据源 | API | 用途 | 限制 |
|--------|-----|------|------|
| **arXiv** | `export.arxiv.org/api/query?search_query=...` | 关键词检索相关预印本 | 免费，无 key |
| **Semantic Scholar** | `api.semanticscholar.org/graph/v1/paper/search` | 引用图谱 + 相关论文 | 免费基础层，100 req/5min |

输出 `RelatedPaperBundle`（≤ 10 篇），含 title、authors、year、abstract、URL、relation_type（`cited_by` / `references` / `keyword_match`）。

### FR-4 R1 推理 Token 处理

| 组件 | 改动 |
|------|------|
| `settings.py` | 新增 `LLM_SUPPORTS_REASONING` 布尔（从模型名自动检测 `r1`，或手动 `LLM_REASONING=true`） |
| `llm.py` | `extract_thinking(response)` → `(thinking_text, content_text)` 分离推理与回答 |
| 各 LLM 调用节点 | 在 output dict 中写入 `thinking_trace`，供 SSE 推送 |

### FR-5 Thinking SSE 事件

新增 SSE 事件类型：

```json
{"type": "thinking", "node": "draft_report_pass1", "content": "让我先分析论文的核心创新点...", "timestamp": "..."}
```

在 `node_start` 和 `node_end` 之间发出，仅对含 LLM 调用的节点。

### FR-6 前端 Markdown 渲染

`ReportPreview.tsx` 从 `<pre>` 升级为 `react-markdown` + `remark-math` + `rehype-katex` + `remark-gfm`，支持：

- GFM 表格
- LaTeX 公式（行内 `$...$`、块级 `$$...$$`）
- 代码高亮
- 超链接

### FR-7 多轮追问对话

| 层 | 实现 |
|----|------|
| **后端** | `POST /tasks/{task_id}/chat`，body: `{"message": "..."}` |
| **上下文构建** | system prompt（角色 + 报告摘要）+ 论文元数据 + 完整报告 + chat history（最近 N 轮） |
| **流式返回** | SSE 或 chunked streaming，逐 token 输出 |
| **前端** | `ChatPanel.tsx`：消息气泡 + 输入框 + 流式渲染；仅在 `isDone` 后出现 |
| **TaskRecord** | 新增 `chat_history: list[ChatMessage]` |

### FR-8 上下文管理

- 对话超过 context limit 时，用 LLM 对报告做一次 summary 压缩
- 保留最近 N 轮完整 + 始终包含 paper metadata + report summary
- 单轮对话输入上限 2000 chars

---

## 5. 非功能需求

| NFR | 目标 |
|-----|------|
| **延迟** | 完整报告生成（含多 pass）< 120s（DeepSeek V3.2 / 方舟） |
| **Token 成本** | 单论文报告 < 80K total tokens（含所有 pass + chat 不算） |
| **兼容性** | DeepSeek 官方（含 R1）、方舟 Ark、OpenAI Chat Completions |
| **向后兼容** | `build_deepseek_chat` 别名保留；现有 v2 测试不破坏 |
| **测试覆盖** | 新增代码 ≥ 80% 行覆盖；所有 prompt 有 mock 测试 |
| **前端兼容** | 现有 GraphView / ProgressBar / ToolLogPanel 继续工作 |

---

## 6. 系统架构

### 6.1 改进后的图拓扑

```
input_parse → ingest_source → extract_document_text → normalize_metadata
  ──(conditional: safe_abort → format_output)──
  → search_related_papers → retrieve_evidence
  → draft_report_outline (Pass 1) → draft_report_expand (Pass 2)
  → repair_report → resolve_citations → verify_claims
  → apply_policy → format_output → END
```

新增 / 变更节点：

| 节点 | 类型 | 说明 |
|------|------|------|
| `search_related_papers` | **新增** | arXiv + Semantic Scholar 双源检索 |
| `draft_report_outline` | **拆分自 `draft_report`** | Pass 1：大纲 + claims + citations (JSON) |
| `draft_report_expand` | **拆分自 `draft_report`** | Pass 2：逐节富 Markdown 展开 |
| `repair_report` | **更新** | REQUIRED_SECTIONS 改为 6 节新结构 |
| 其余节点 | 不变 | resolve_citations / verify_claims / apply_policy / format_output |

### 6.2 State Schema 变更

`AgentState` 新增字段：

```python
related_papers: list[RelatedPaper] | None
thinking_traces: Annotated[list[ThinkingTrace], operator.add]
```

`TaskRecord` 新增字段：

```python
chat_history: list[ChatMessage]
```

### 6.3 数据模型新增

```python
class RelatedPaper(BaseModel):
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    url: str
    relation_type: Literal["references", "cited_by", "keyword_match"]
    source: Literal["arxiv", "semantic_scholar"]

class RelatedPaperBundle(BaseModel):
    papers: list[RelatedPaper]
    query_keywords: list[str]

class ThinkingTrace(BaseModel):
    node: str
    content: str
    timestamp: str

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str
```

---

## 7. API 变更

### 7.1 现有端点（不变）

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /tasks` | POST | 提交报告任务 |
| `GET /tasks` | GET | 列表 |
| `GET /tasks/{id}` | GET | 任务详情 |
| `GET /tasks/{id}/events` | SSE | 实时事件流 |

### 7.2 新增端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /tasks/{id}/chat` | POST | 追问对话 |

**Request:**

```json
{"message": "请展开分析 positional encoding 的局限性"}
```

**Response:** SSE stream 或 JSON：

```json
{
  "role": "assistant",
  "content": "...",
  "thinking": "..."
}
```

### 7.3 SSE 事件新增

| 事件 type | 触发时机 | payload |
|-----------|----------|---------|
| `thinking` | LLM 节点推理过程中 | `{node, content, timestamp}` |
| `chat_token` | 追问对话流式输出 | `{content, done}` |

---

## 8. 前端变更

### 8.1 新增组件

| 组件 | 位置 | 说明 |
|------|------|------|
| `ThinkingPanel.tsx` | ToolLogPanel 右侧 tab 或独立可折叠面板 | 展示按节点分组的推理 trace |
| `ChatPanel.tsx` | ReportPreview 下方 | 多轮对话 UI：气泡消息 + 输入框 + 流式渲染 |

### 8.2 现有组件改动

| 组件 | 改动 |
|------|------|
| `ReportPreview.tsx` | `<pre>` → `react-markdown` + `remark-math` + `rehype-katex` + `remark-gfm` |
| `useTaskSSE.ts` | 处理 `type === 'thinking'` 和 `type === 'chat_token'` 事件 |
| `App.tsx` | 引入 ThinkingPanel、ChatPanel；布局调整 |

### 8.3 新增依赖

```
react-markdown
remark-math
remark-gfm
rehype-katex
katex (CSS)
```

---

## 9. 交付计划

### Phase 1: 报告质量（P0）

| 任务 | 文件 | 产出 |
|------|------|------|
| 1a. 设计新 System Prompt 体系 | `src/agent/prompts_v2.py` (新建) | REPORT_ROLE_PREAMBLE + OUTLINE + SECTION_EXPAND |
| 1b. 多 Pass 生成 | `src/graph/nodes/draft_report.py` (重写) | Pass 1 (outline JSON) + Pass 2 (per-section Markdown) |
| 1c. 报告模型 & 渲染 | `src/models/report.py`, `src/agent/report.py` | 富 Markdown section 值；新 `_final_report_to_markdown` |
| 1d. 增加论文文本输入量 | `draft_report.py` | `[:5000]` → `[:32000]` |
| 1e. repair_report 更新 | `src/graph/nodes/repair_report.py` | REQUIRED_SECTIONS 对齐新 6 节 |
| 1f. 前端 Markdown 渲染 | `frontend/src/components/ReportPreview.tsx` | react-markdown + remark-math + rehype-katex |

**验收标准:** 对 `1706.03762` 生成报告 ≥ 300 行，含表格 ≥ 2、LaTeX 公式 ≥ 3、代码块 ≥ 1。

### Phase 2: DeepSeek R1 兼容 + 思考可视化（P0）

| 任务 | 文件 | 产出 |
|------|------|------|
| 2a. R1 推理提取 | `src/agent/llm.py`, `src/agent/settings.py` | `extract_thinking()` + `LLM_SUPPORTS_REASONING` |
| 2b. Thinking SSE 事件 | `src/api/routes/tasks.py`, `src/graph/state.py` | `thinking` 事件类型 + `ThinkingTrace` |
| 2c. ThinkingPanel 前端 | `frontend/src/components/ThinkingPanel.tsx` | 可折叠推理面板 |

**验收标准:** 使用 R1 模型时，前端可见推理文本；非 R1 模型正常工作不报错。

### Phase 3: 多论文文献检索（P1）

| 任务 | 文件 | 产出 |
|------|------|------|
| 3a. search_related_papers 节点 | `src/graph/nodes/search_related.py` (新建) | arXiv API + Semantic Scholar API |
| 3b. 状态 & 图接线 | `src/graph/state.py`, `src/graph/builder.py` | `related_papers` 字段 + 新节点插入 |
| 3c. Prompt 整合 | `src/agent/prompts_v2.py`, `draft_report.py` | 相关论文 metadata 注入「背景与相关工作」prompt |

**验收标准:** 生成报告的「背景与相关工作」含 ≥ 5 篇外部论文、Markdown 表格、URL 可点击。

### Phase 4: 多轮追问对话（P1）

| 任务 | 文件 | 产出 |
|------|------|------|
| 4a. Chat 后端 | `src/api/routes/tasks.py` | `POST /tasks/{id}/chat` + chat_history |
| 4b. ChatPanel 前端 | `frontend/src/components/ChatPanel.tsx` (新建) | 消息气泡 + 流式 + isDone 后显示 |
| 4c. 上下文管理 | `src/agent/chat_context.py` (新建) | 报告 summary + history truncation |

**验收标准:** 报告完成后可追问 ≥ 3 轮，回答引用报告内容且上下文连贯。

### 依赖关系

```
Phase 1 ──→ Phase 2（prompt 体系是基础）
Phase 1 ──→ Phase 3（报告结构确定后才能接相关论文）
Phase 2 ─┐
          ├→ Phase 4（需要 SSE 基础设施 + 报告 context）
Phase 3 ─┘
```

Phase 2 和 Phase 3 可在 Phase 1 完成后并行。

---

## 10. 文件变更清单

### 新建文件

| 文件路径 | 所属 Phase |
|----------|-----------|
| `src/agent/prompts_v2.py` | 1 |
| `src/graph/nodes/search_related.py` | 3 |
| `src/agent/chat_context.py` | 4 |
| `frontend/src/components/ThinkingPanel.tsx` | 2 |
| `frontend/src/components/ChatPanel.tsx` | 4 |

### 修改文件

| 文件路径 | 所属 Phase | 变更范围 |
|----------|-----------|----------|
| `src/graph/nodes/draft_report.py` | 1 | 全部重写（多 pass） |
| `src/graph/nodes/repair_report.py` | 1 | REQUIRED_SECTIONS 更新 |
| `src/models/report.py` | 1 | 无 schema 破坏性改动，section 值从短文本变为富 Markdown |
| `src/agent/report.py` | 1 | `_final_report_to_markdown` 增强 |
| `src/agent/llm.py` | 2 | 新增 `extract_thinking()` |
| `src/agent/settings.py` | 2 | 新增 `LLM_SUPPORTS_REASONING` |
| `src/graph/state.py` | 2, 3 | 新增 `related_papers`, `thinking_traces` |
| `src/graph/builder.py` | 3 | 插入 `search_related_papers` 节点 |
| `src/api/routes/tasks.py` | 2, 4 | thinking SSE + chat endpoint |
| `frontend/src/components/ReportPreview.tsx` | 1 | Markdown 渲染器升级 |
| `frontend/src/hooks/useTaskSSE.ts` | 2 | 处理 thinking / chat_token 事件 |
| `frontend/src/App.tsx` | 2, 4 | 引入新组件 |
| `.env.example` | 2 | 新增 `LLM_SUPPORTS_REASONING` 说明 |

---

## 11. 成功指标

| 指标 | 目标 | 度量方式 |
|------|------|----------|
| 报告长度 | ≥ 300 行 Markdown | `wc -l` on generated report |
| 报告结构 | 6 大节 + 子节 | 正则匹配 `## I.` ~ `## VI.` |
| 表格数量 | ≥ 2 | `grep -c '|' report` |
| 公式数量 | ≥ 3 | `grep -c '\$\$' report` |
| 外部引用数 | ≥ 5 篇不同论文 URL | unique URL count in citations |
| 追问可用 | ≥ 3 轮 | 手动测试 |
| R1 思考展示 | thinking panel 有内容 | 使用 R1 模型手动验证 |
| 端到端延迟 | < 120s | 计时测试 |
| 测试通过 | 现有 155 + 新增 ≥ 20 tests | `pytest` |
| Token 成本 | < 80K per report | `tokens_used` from state |

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| DeepSeek V3.2 对长 Markdown 输出质量不稳定 | 报告部分节生成失败 | repair_report 兜底 + per-section 独立调用隔离失败 |
| Semantic Scholar API 限速 (100 req/5min) | 并发测试被拒 | 缓存结果 + 指数退避 + 降级为仅 arXiv |
| R1 `reasoning_content` 格式随 API 版本变化 | 思考提取失败 | `extract_thinking` 做 try-except 降级，不影响主流程 |
| 多 Pass 生成增加 token 成本 | 超出预算 | 监控 `tokens_used`；Pass 2 仅对 4 个核心节展开，小节合并 |
| 追问对话 context 溢出 | LLM 报错 | summary 压缩 + history truncation |
| react-markdown / KaTeX 前端包体积增大 | 首屏加载慢 | 动态 import / code splitting |

---

## 附录 A: System Prompt 设计（草稿）

### A.1 REPORT_ROLE_PREAMBLE

```
你是一位资深学术审稿人兼论文精读助手。你的输出面向有研究经验的读者，
需要达到接近顶会水准的分析深度。你必须：
- 以严肃 reviewer 视角评估 novelty、实验充分性、局限性
- 区分「来自前驱的改造」与「本文独立创新」
- 所有事实声明标注引用来源（[markdown link](url) 格式）
- 不确定的内容必须标注「待核实」
- 输出中文，学术语气，避免口语化
```

### A.2 OUTLINE_SYSTEM_PROMPT（Pass 1）

```
基于以下论文全文和相关文献信息，生成精读报告大纲。输出 JSON：

{
  "sections": {
    "I. 摘要与研究动机": "3-5 句概括：摘要要点、问题定义、研究空白",
    "II. 背景与相关工作": "列出需要对比的相关论文（≥5篇），novelty 评级方向",
    "III. 方法": "列出需要逐一解析的核心模块名（≥3个），每个标注关键公式编号",
    "IV. 实验": "列出主要实验表格/图、消融实验、需要分析的指标",
    "V. 讨论与未来方向": "列出作者提到的局限性 + 你发现的未提及问题",
    "VI. 总结和展望": "一句话总结 + 范式意义"
  },
  "claims": [...],
  "citations": [...]
}
```

### A.3 SECTION_EXPAND_PROMPT（Pass 2，以「III. 方法」为例）

```
你正在撰写论文精读报告的「III. 方法」章节。基于以下大纲和论文原文，
输出该章节的完整 Markdown 内容。要求：

1. 总体结构与框架：用文字 pipeline 或流程描述整体架构
2. 模块逐一解析：每个核心模块需包含
   - 功能与设计目的
   - 关键公式（LaTeX $$ 格式）+ 符号表
   - 直觉解释（为什么这样设计）
   - 原代码位置（如有）
   - 创新归属判断（来自前驱 vs 本文独立）
3. 损失函数与优化策略
4. 复杂度与收敛性分析

用 Markdown 表格对比不同方法的复杂度。用 LaTeX 写所有公式。
用 ``` 代码块写伪代码。所有声明标注引用链接。
```

### A.4 CHAT_SYSTEM_PROMPT

```
你是论文精读助手。以下是已生成的精读报告摘要和原论文信息。
用户会就报告内容提出深入问题，请基于报告和论文原文回答。
如果需要补充报告未涉及的内容，请明确标注「报告未覆盖，以下为补充分析」。
回答使用中文，保持学术语气。
```

---

## 附录 B: 与 v2 文档的关系

| v2 文档 | v3 处理 |
|---------|---------|
| `docs/specs/2026-03-29-v2-architecture-design.md` | 保留为基础架构参考，v3 在其上扩展 |
| `docs/plans/2026-03-29-v2-implementation.md` | v2 实施已完成，v3 不修改此文件 |
| `docs/architecture.md` | Phase 完成后更新目录结构 |
| `docs/evals.md` | Phase 1 完成后更新 eval cases（增加报告质量评估维度） |

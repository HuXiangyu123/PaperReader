# PaperReader Agent

> 面向科研场景的多阶段 LLM Agent 系统：输入研究主题，自动完成需求澄清 → 检索规划 → 多源论文获取 → 结构化抽取 → 上下文压缩 → 综述生成 → Review 把关 → 报告持久化，输出带可追溯引用的结构化 Markdown 综述报告。

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **多阶段工作流** | 8 节点 StateGraph：clarify → search_plan → search → extract → compress → draft → review → persist |
| **三源并行检索** | SearXNG + arXiv API + DeepXiv 并行搜索，自动去重 |
| **上下文压缩** | extract_compression_node，87% 压缩率（30k chars → 4k chars） |
| **引用验证闭环** | resolve_citations → verify_claims → apply_policy，claim-level grounding |
| **Source Tier 分类** | A/B/C/D 四级权威度评估 |
| **三层评测体系** | Layer 1 (hard rules) → Layer 2 (LLM judge) → Layer 3 (human review) |
| **Circuit Breaker** | 熔断器保护外部 API 调用 |
| **Entropy Management** | 代码腐化检测（死代码、约束违反、文档漂移） |

---

## 技术栈

```
LLM 调用        DeepSeek (OpenAI-compatible) / Claude / GPT
Agent 编排      LangGraph StateGraph + LangChain Core
后端框架        FastAPI + Uvicorn + Pydantic v2
持久化          PostgreSQL + SQLAlchemy 2 + JSONB
向量检索        FAISS (本地) / pgvector (待启用)
前端            React 19 + TypeScript 5 + @xyflow/react
搜索聚合        SearXNG (多引擎并行)
文档解析        pdfplumber + arXiv API
```

---

## 快速开始

### 1. 环境配置

```bash
conda create -n paper-reader python=3.11 -y
conda activate paper-reader
pip install -e .
```

### 2. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API Key：

```ini
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_API_BASE=https://api.deepseek.com
```

### 3. 启动服务

**启动后端**：
```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

**启动前端**：
```bash
cd frontend && npm install && npm run dev
```

### 4. 使用

打开浏览器访问 `http://localhost:5173`，你将看到可视化工作流界面：

- **创建任务**：输入 arXiv 链接/ID 或研究主题
- **实时追踪**：SSE 推送，节点状态实时更新
- **可视化**：@xyflow/react 渲染 LangGraph DAG
- **查看报告**：Markdown 渲染，支持 LaTeX 公式

---

## 工作流图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Research Graph (8 节点)                        │
│                                                                     │
│  ┌─────────┐   ┌──────────────┐   ┌───────┐   ┌────────────────┐   │
│  │clarify  │──→│ search_plan  │──→│search │──→│    extract     │   │
│  └─────────┘   └──────────────┘   └───┬───┘   └───────┬────────┘   │
│       │                                  │              │           │
│       │ needs_followup?                  │              ↓           │
│       ↓（若需要追问）                     │       ┌─────────────┐     │
│      END                           ┌─────▼─────┐  │  compress   │    │
│                                  │  三源并行   │  └──────┬──────┘     │
│                                  │  去重入库   │         │            │
│                                  └────────────┘         ↓            │
│                                                      ┌───────┐       │
│                                                      │ draft │       │
│                                                      └───┬───┘       │
│                                                          │           │
│                                             review_passed? ↓          │
│                                         ┌─────────────────┐           │
│                                         │     review      │           │
│                                         └────────┬────────┘           │
│                                                  │                    │
│                                                  ↓                    │
│                                         ┌─────────────────┐            │
│                                         │persist_artifacts│            │
│                                         └─────────────────┘            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 项目结构

```
PaperReader Agent/
├── src/
│   ├── agent/          # Agent 编排、Circuit Breaker
│   ├── research/       # Research Graph (8 节点工作流)
│   │   ├── agents/     # 多 Agent 协作
│   │   ├── graph/     # StateGraph 构建、节点实现
│   │   └── services/  # ReviewerService, CompressionService
│   ├── tools/          # arXiv API / SearXNG / MCP Adapter
│   ├── skills/         # Skills 框架
│   ├── memory/         # 短期/工作区/长期三层记忆
│   ├── db/             # PostgreSQL 持久化
│   ├── entropy/        # Entropy Management System
│   └── api/            # FastAPI 入口
├── frontend/           # React 19 + @xyflow/react 可视化
├── eval/               # 三层评测框架
└── docs/               # 架构文档、Issue 追踪
```

---

## 技术亮点

1. **多阶段 StateGraph 工作流**：8 节点 + 11 节点双图并行
2. **Context Compression Pipeline**：87% 压缩率，解决 context window 限制
3. **引用验证闭环（Claim-Level Grounding）**：resolve → verify → policy
4. **三源并行检索**：无 API key，多引擎聚合
5. **三层 Eval 体系**：hard rules → LLM judge → human review
6. **Circuit Breaker + Entropy Management**：生产级稳定性保障

---

## 文档

详细技术文档见 [docs/面试/tech_part/README.md](docs/面试/tech_part/README.md)

---

## License

MIT

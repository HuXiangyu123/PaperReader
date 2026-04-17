# PaperReader Agent

> 面向科研场景的多阶段 LLM Agent 系统：输入研究主题，自动完成需求澄清 → 检索规划 → 多源论文获取 → 结构化抽取 → 上下文压缩 → 综述生成 → Review 把关 → 报告持久化，输出带可追溯引用的结构化 Markdown 综述报告。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)

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
LLM Provider    DeepSeek (OpenAI-compatible) / Claude / GPT
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
# 编辑 .env，填入 DeepSeek API Key
```

```ini
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### 3. 启动服务

**CLI 模式**（交互式）：
```bash
python -m src.agent.cli
```

**API 模式**：
```bash
uvicorn src.api.app:app --host 0.0.0.0 --port 8000
```

**API 调用示例**：

```bash
# 生成研究报告（arXiv URL）
curl -X POST "http://127.0.0.1:8000/report" \
  -H "Content-Type: application/json" \
  -d '{"arxiv_url_or_id": "https://arxiv.org/abs/1706.03762"}'

# 上传 PDF 生成报告
curl -X POST "http://127.0.0.1:8000/report/upload_pdf" \
  -F "file=@./paper.pdf"

# 调研主题（Research Graph）
curl -X POST "http://127.0.0.1:8000/research/start" \
  -H "Content-Type: application/json" \
  -d '{"topic": "调研 AI Agent 在医疗领域的进展"}'
```

---

## 项目架构

```
PaperReader Agent/
├── src/
│   ├── agent/          # Agent 编排、报告生成、Circuit Breaker
│   ├── research/       # Research Graph (8 节点工作流)
│   │   ├── agents/     # 多 Agent 协作 (ClarifyAgent, SearchPlanAgent...)
│   │   ├── graph/     # StateGraph 构建、节点实现
│   │   ├── prompts/   # Prompt 模板
│   │   └── services/  # ReviewerService, CompressionService
│   ├── tools/          # arXiv API / SearXNG / DeepXiv / MCP Adapter
│   ├── skills/         # Skills 框架 + 9 个内置 Skill
│   ├── graph/          # Report Graph (11 节点，单篇论文报告)
│   ├── memory/         # 短期/工作区/长期三层记忆
│   ├── db/             # PostgreSQL 持久化 (TaskSnapshot, ChunkStore)
│   ├── models/         # Pydantic 模型定义
│   ├── entropy/        # Entropy Management System
│   └── api/            # FastAPI 入口 + Routes
├── frontend/           # React 19 + @xyflow/react 可视化
├── eval/               # 三层评测框架
└── docs/               # 架构文档、Issue 追踪
```

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

## 当前成熟度

| 阶段 | 功能 | 状态 |
|------|------|------|
| Phase 1-3 | 8 节点 Research Graph + 11 节点 Report Graph | ✅ 成熟 |
| Phase 1-3 | 三源并行检索 + 批量 LLM 抽取 | ✅ 成熟 |
| Phase 1-3 | Context Compression (87% 压缩率) | ✅ 成熟 |
| Phase 1-3 | Citation Resolution + Review Gate | ⚠️ 待优化 |
| Phase 1-3 | PostgreSQL 持久化 + SSE 推送 | ✅ 成熟 |
| Phase 4 | Multi-Agent 协作 | ⚠️ 需重构 |
| Phase 4 | Skills 框架 | ⚠️ 未接入主链路 |
| Phase 4 | MCP Server | ⚠️ transport 实现，无实际 server |

---

## 已知问题与改进方向

### P0 问题（待修复）

| 问题 | 说明 |
|------|------|
| LangGraph 合规性 (24%) | 手工 `AgentSupervisor` 替代官方 `create_supervisor` |
| review gate 过宽 | 9/9 ungrounded claims 仍返回 passed |
| Skills 未接入主链路 | 9 个 Skill 定义了但几乎没被使用 |

### 待实现特性

| 特性 | 优先级 |
|------|--------|
| 动态 Re-plan 机制 | P1 |
| DAG fan-out 并行 | P2 |
| MCP server 实际配置 | P1 |

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

- [技术文档目录](docs/面试/tech_part/README.md) — 按模块拆分的深度技术文档
- [项目概览](docs/面试/tech_part/01-项目概览.md) — 定位、业务背景、成熟度
- [技术栈详解](docs/面试/tech_part/02-技术栈.md) — 选型理由、代码流程、优势
- [工作流架构](docs/面试/tech_part/03-工作流架构.md) — 8 节点详解、条件降级
- [多智能体协作](docs/面试/tech_part/04-多智能体协作.md) — ⚠️ LangGraph 合规性问题
- [Memory 系统](docs/面试/tech_part/05-Memory系统.md) — 三层记忆、状态流转
- [RAG 检索架构](docs/面试/tech_part/06-RAG检索架构.md) — 三层检索 + Reranker
- [评测体系](docs/面试/tech_part/08-评测体系.md) — Layer 1/2/3 分层评测

---

## License

MIT

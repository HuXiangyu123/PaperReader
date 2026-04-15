# PaperReader Agent — 技术文档总览

> 本目录按技术模块拆分，每个模块一份独立文档，包含代码流程、技术栈选型、量化指标。

---

## 目录结构

```
docs/面试/tech_part/
├── README.md                        ← 本文件
├── 01-项目概览.md                   ← 项目定位、业务背景、技术栈总览
├── 02-技术栈.md                     ← 核心技术栈选型详解
├── 03-工作流架构.md                ← Research Graph 7 节点工作流
├── 04-多智能体协作.md              ← Multi-Agent 协作体系
├── 05-Memory系统.md                ← 短期/工作区/长期记忆
├── 06-RAG检索架构.md               ← 三层检索 + Reranker
├── 07-Grounding验证体系.md          ← 三段式引用验证
├── 08-评测体系.md                  ← Layer 1/2/3 分层评测
├── 09-工具与Skills.md              ← 工具注册 + Skills 框架 + MCP
├── 10-CircuitBreaker设计.md         ← 熔断器实现分析（已实现）
├── 11-ContextCompression设计.md      ← 上下文压缩设计（待实现）
└── 12-EntropyManagement设计.md       ← 熵管理系统设计（待实现）
```

---

## 快速导航

### 已实现技术（生产可用）

| 模块 | 文档 | 成熟度 |
|------|------|--------|
| Research Graph 工作流 | [03-工作流架构.md](03-工作流架构.md) | ✅ 生产可用 |
| Multi-Agent 协作 | [04-多智能体协作.md](04-多智能体协作.md) | ✅ Supervisor 实现 |
| 三源检索 | [06-RAG检索架构.md](06-RAG检索架构.md) | ✅ 三源并行 |
| Citation Resolution | [07-Grounding验证体系.md](07-Grounding验证体系.md) | ✅ 生产可用 |
| 三层 Eval | [08-评测体系.md](08-评测体系.md) | ✅ Layer 1/2 |
| Skills 框架 | [09-工具与Skills.md](09-工具与Skills.md) | ✅ 9 个内置 skills |
| Circuit Breaker | [10-CircuitBreaker设计.md](10-CircuitBreaker设计.md) | ✅ 已实现 |
| MCP Adapter | [09-工具与Skills.md](09-工具与Skills.md) | ✅ stdio+HTTP transport |

### 待实现特性

| 特性 | 文档 | 优先级 |
|------|------|--------|
| Context Compression | [11-ContextCompression设计.md](11-ContextCompression设计.md) | P0 |
| Entropy Management | [12-EntropyManagement设计.md](12-EntropyManagement设计.md) | P1 |
| 动态 Re-plan 机制 | — | P1 |
| DAG fan-out 并行 | — | P2 |

---

## 技术文档撰写规范

每份技术文档包含：

1. **技术选型理由** — 为什么用这个技术，解决了什么问题
2. **核心代码流程** — 关键函数的代码块（带行号引用）
3. **架构流图** — 用文字描述关键流程
4. **量化指标** — 有 metrics 的模块必须分析数值和 benchmark
5. **技术优势** — 该技术带来的具体收益

---

## 更新记录

| 日期 | 更新内容 |
|------|---------|
| 2026-04-14 | 初始创建，按 12 个模块拆分 |

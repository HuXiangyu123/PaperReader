# PaperReader Agent — Memory 与状态管理

---

## 1. 整体 Memory 架构

### 1.1 三层 Memory 模型

| 层次 | 存储介质 | 生命周期 | 作用 |
|------|---------|---------|------|
| **短期记忆（Working Memory）** | `AgentState` TypedDict | 单任务执行期间 | 节点间传递中间产物 |
| **工作区持久化（Workspace）** | PostgreSQL JSONB + workspace 文件 | 单任务生命周期 | 快照、报告、chunks |
| **长期记忆（Long-term）** | `.memory/` 目录（JSON） | 跨任务 | 跨会话语义/情景记忆 |

### 1.2 Memory 相关文件

```
src/memory/
├── __init__.py
└── manager.py          # MemoryManager — 管理 episodic + semantic memory

.memory/                 (workspace 外）
├── episodic/           # 情景记忆：每次任务的事件序列
│   └── ws_{task_id}.json
├── semantic/           # 语义记忆：跨任务提取的知识
│   └── ws_{workspace_id}.json
```

---

## 2. 短期记忆：AgentState

**文件**：`src/research/graph/state.py`

```python
from typing import TypedDict, Annotated
import operator

class AgentState(TypedDict):
    """Research Graph 的运行时状态载体"""

    # 任务标识
    task_id: str
    workspace_id: str | None

    # 输入输出
    raw_input: str
    brief: ResearchBrief | None
    search_plan: SearchPlan | None
    rag_result: RagResult | None

    # 中间产物
    paper_cards: list[PaperCard]
    draft_report: DraftReport | None
    resolved_report: DraftReport | None
    verified_report: DraftReport | None
    final_report: FinalReport | None
    review_feedback: ReviewFeedback | None

    # 量化指标（累加）
    tokens_used: Annotated[dict, operator.add]
    """每个节点的 token 消耗，operator.add 自动合并"""

    # 警告列表（累加）
    warnings: Annotated[list, operator.add]
    """每个节点产生的 warnings，operator.add 自动追加"""

    # 运行时事件
    node_events: list[dict]
    """SSE 事件列表，用于前端可视化"""
```

**关键设计**：
- `Annotated[dict, operator.add]` 和 `Annotated[list, operator.add]`：每次节点返回 patch 时，LangGraph 自动将返回值与当前状态合并
- 所有字段显式 `None | Type` 类型标注：类型安全

---

## 3. 工作区持久化：PostgreSQL + TaskSnapshot

**文件**：`src/db/task_persistence.py`

```python
class TaskPersistence:
    """任务持久化服务"""

    async def upsert_task_snapshot(
        self,
        task_id: str,
        stage: str,
        state_snapshot: dict,
    ) -> None:
        """
        任务快照：完整 AgentState JSONB 持久化

        ON CONFLICT DO UPDATE：任务重跑时覆盖而非重复
        """
        async with get_async_session() as session:
            snapshot = TaskSnapshot(
                task_id=task_id,
                stage=stage,
                state_snapshot=state_snapshot,  # JSONB 列
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            # SQLAlchemy upsert
            stmt = insert(TaskSnapshot).values(**snapshot.__dict__)
            stmt = stmt.on_conflict_do_update(
                index_elements=["task_id"],
                set_={
                    "stage": stmt.excluded.stage,
                    "state_snapshot": stmt.excluded.state_snapshot,
                    "updated_at": datetime.utcnow(),
                },
            )
            await session.execute(stmt)
            await session.commit()
```

**TaskSnapshot 模型**（`src/db/models.py`）：

```python
class TaskSnapshot(Base):
    __tablename__ = "task_snapshots"

    task_id: Mapped[str] = Column(String, primary_key=True)
    workspace_id: Mapped[str] = Column(String, nullable=True)
    stage: Mapped[str] = Column(String, nullable=False)
    # JSONB：存储完整 AgentState，无需预定义 schema
    state_snapshot: Mapped[dict] = Column(JSONB, nullable=False)
    created_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

---

## 4. 长期记忆：.memory 目录

**文件**：`src/memory/manager.py`

```python
class MemoryManager:
    """跨任务记忆管理器"""

    def __init__(self, memory_dir: Path = Path(".memory")):
        self.memory_dir = memory_dir
        self.episodic_dir = memory_dir / "episodic"
        self.semantic_dir = memory_dir / "semantic"

    async def store_episodic(self, task_id: str, events: list[dict]) -> None:
        """存储情景记忆：任务执行的事件序列"""
        path = self.episodic_dir / f"ws_{task_id}.json"
        await self._write_json(path, {
            "task_id": task_id,
            "events": events,
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def store_semantic(self, workspace_id: str, knowledge: dict) -> None:
        """存储语义记忆：跨任务提取的知识"""
        path = self.semantic_dir / f"ws_{workspace_id}.json"
        await self._write_json(path, {
            "workspace_id": workspace_id,
            "knowledge": knowledge,
            "updated_at": datetime.utcnow().isoformat(),
        })

    async def retrieve_semantic(self, workspace_id: str, query: str) -> list[dict]:
        """基于查询检索语义记忆"""
        path = self.semantic_dir / f"ws_{workspace_id}.json"
        if not path.exists():
            return []

        data = await self._read_json(path)
        # 简单关键词匹配（未来可升级为向量检索）
        return [k for k in data.get("knowledge", []) if query.lower() in str(k).lower()]
```

---

## 5. State 流转图

```
用户输入 (raw_input)
  │
  ▼
clarify_node(state={}) ──────────────────────────┐
  │ 返回 {"brief": ResearchBrief}                 │
  ▼                                            │
search_plan_node(state={brief}) ─────────────┐   │
  │ 返回 {"search_plan": SearchPlan}          │   │
  ▼                                          │   │
search_node(state={search_plan}) ──────────┐ │   │
  │ 返回 {"rag_result": RagResult}           │ │   │
  ▼                                          │ │   │
extract_node(state={rag_result}) ──────────┐ │ │   │
  │ 返回 {"paper_cards": list[PaperCard]}   │ │ │   │
  ▼                                          │ │ │   │
draft_node(state={paper_cards}) ───────────┐ │ │ │   │
  │ 返回 {"draft_report": DraftReport}      │ │ │ │   │
  ▼                                          │ │ │ │   │
review_node(state={draft_report}) ──────────┐ │ │ │ │   │
  │ 返回 {"final_report": FinalReport,      │ │ │ │ │   │
  │       "review_feedback": ReviewFeedback} │ │ │ │ │   │
  ▼                                          │ │ │ │ │   │
persist_artifacts_node(state={final_report}) ─┘ │ │ │ │   │
  │ 写入 PostgreSQL Snapshot                 │ │ │ │ │   │
  ▼                                            ▼ ▼ ▼ ▼ ▼

tokens_used: {"clarify": 200, "search_plan": 150, ...}  ← operator.add 累加
warnings: ["arXiv API 超时", "LLM JSON 解析失败"]      ← operator.add 累加
```

---

## 6. 状态持久化 vs. 内存状态对比

| 维度 | PostgreSQL Snapshot | In-memory dict | .memory/ JSON |
|------|-------------------|----------------|---------------|
| **用途** | 任务快照恢复 | 运行时传递 | 跨任务记忆 |
| **生命周期** | 持久 | 单次任务 | 持久 |
| **查询能力** | 可 SQL 查询 | 无 | 手动读取 |
| **Schema** | 预定义 ORM | TypedDict | 灵活 JSON |
| **恢复速度** | 慢（需 DB 连接） | 快 | 中等 |

---

## 7. 优点与局限

### 7.1 优点

| 优点 | 说明 |
|------|------|
| **JSONB 灵活性** | AgentState 结构变化时无需 ALTER TABLE，schema-free |
| **累加语义** | `operator.add` 确保 tokens_used 和 warnings 自然累加 |
| **Upsert 语义** | 任务重跑时覆盖快照，避免重复记录 |
| **三层分离** | 短期/工作区/长期分离，各司其职 |

### 7.2 局限

| 局限 | 影响 |
|------|------|
| **内存 dict 无持久化** | `_tasks` in-memory dict 随进程消失 |
| **.memory/ 未参与主流程** | 跨任务记忆未被工作流使用 |
| **向量检索未启用** | 跨任务语义检索仍用关键词匹配 |
| **无记忆压缩** | 长期记忆无限增长，无淘汰策略 |

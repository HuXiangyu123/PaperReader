# Research 模式任务执行问题 Issue 报告

> 生成时间：2026-04-10
> 最后更新：2026-04-11（Codex 修复后验证通过）
> 涉及模块：`src/api/routes/tasks.py`、`src/research/policies/clarify_policy.py`、`src/research/prompts/clarify_prompt.py`、`src/agent/settings.py`
> 调试方法：系统调试（Systematic Debugging），遵循"先找根因，再修复"原则

---

## 问题概述

用户提交 research 任务（如"调研RAG"）后，任务状态一直卡在 `pending` 或 `running`，无法推进到 `clarify` → `search_plan` 阶段。

经过系统调试，发现存在 **2 个独立问题**：

1. **ClarifyAgent LLM prompt 导致 `needs_followup=True`**（Phase 1 根因）
2. **Task 后台执行图挂死**（Phase 2 根因）

---

## Issue 1：ClarifyAgent 对简单 topic 查询保守地要求追问

### 严重程度：P1（功能阻塞）

### 现象
用户输入"调研RAG"、"RAG调研"等简单 topic 查询后：
- ClarifyAgent 返回 `needs_followup=True`
- 工作流停滞在 `clarify` 阶段
- 前端弹出追问表单

### 根因分析（Phase 1）

#### 测试证据
```python
# 测试代码
from src.research.agents.clarify_agent import run as run_clarify_agent
from src.research.research_brief import ClarifyInput
import warnings

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    inp = ClarifyInput(raw_query='调研RAG')
    result = run_clarify_agent(inp)
    # LLM 返回：needs_followup=True, confidence=0.28
```

#### 根因
`ClarifyAgent` 的 **system prompt** 包含两条互相冲突的规则：

1. "do not guess silently → surface ambiguities"
2. "If ambiguity is significant → set `needs_followup=true`"

LLM 将"输出格式未指定"（如 user 只给 topic）判定为"significant ambiguity"，触发 `needs_followup=True`。

### 修复方案（已实施）

**文件 1：`src/research/prompts/clarify_prompt.py`**

修改 `CLARIFY_SYSTEM_PROMPT`，增加明确的决策规则：
- 清晰 topic keyword 时直接推断 `desired_output="survey_outline"`，不视为 ambiguity
- `needs_followup=true` 仅在"研究领域本身不明确"时设置

增加 few-shot 示例：
- Example 2：`"调研RAG"` → `needs_followup=False, desired_output=survey_outline`
- Example 3：`"RAG调研"` → `needs_followup=False, desired_output=survey_outline`
- Example 4（真正模糊）：`"帮我看看最近有什么好方法"` → `needs_followup=True`

**文件 2：`src/research/policies/clarify_policy.py`**

调整 `_is_topic_specific()` 函数，简化 topic 判定逻辑：
- 30 字符以内的非问句 → topic 特定
- 10 字符以上 → topic 特定

调整 `to_limited_brief()` 默认值：
- 未指定 `desired_output` 时，默认 `survey_outline`（而非 `research_brief`）
- 只在 topic 也模糊时才追加 `desired_output` ambiguity

调整 confidence 评分：
- 特定 topic + 成功推断输出 → 0.68
- 特定 topic + 需轻微澄清 → 0.52
- 其他 → 0.25

**修复后验证：**
```python
# policy fallback 验证
to_limited_brief('调研RAG')
# → needs_followup=False, confidence=0.68, desired_output='survey_outline'

to_limited_brief('RAG调研')
# → needs_followup=False, confidence=0.68, desired_output='survey_outline'
```

### 状态：✅ 已修复（但需要验证 LLM 层是否同步生效）

### 风险备注
- 修复后 ClarifyAgent 使用**更新后的 prompt** 调用 LLM
- 需重新测试端到端流程，确认 LLM 层也返回正确结果
- 如果 LLM 仍保守，需进一步调整 prompt 或 few-shot 示例

---

## Issue 2：Task 后台执行图挂死

### 严重程度：P0（系统不可用）

### 现象
1. `POST /tasks` 返回 `pending` 后，任务永不进入 `running` 状态
2. 查看 `GET /tasks/{id}` → `status=running` 但 `node_events=0`
3. `GET /tasks/{id}/trace` → 无 trace 数据

### 根因分析（Phase 2 调试过程）

#### 调试链路（系统调试方法论）

| 步骤 | 证据 | 结论 |
|------|------|------|
| 1. 检查 `_run_graph` 是否被调用 | 加 `print()` → 调用正常 | handler 触发正常 |
| 2. 检查 `_run_graph_sync_wrapper` 是否被调用 | 加文件写入 → 调用正常 | thread pool 触发正常 |
| 3. 检查 `graph.stream()` 是否执行 | 裸 Python 测试 → 4 chunks 正常返回 | graph 逻辑正常 |
| 4. 检查 server 内的 `graph.stream()` | `/graph-test` endpoint → 挂死，无 chunk 返回 | **在 server 上下文挂死** |
| 5. 检查 LLM 是否可用 | `/llm-test` endpoint → 4.8s 返回正常 | LLM 本身正常 |
| 6. 检查 `_bg_executor` 提交 | `_bg_executor.submit()` → 正常提交 | thread pool 正常 |
| 7. 检查 server 外的等效调用 | 裸 Python → 正常完成 | **仅 server 上下文挂死** |

#### 最终定位

**在 server 上下文中（uvicorn 异步 handler 调用链内），`graph.stream()` 挂死在 `clarify` → `search_plan` 的节点切换阶段。**

```python
# 挂死位置
for chunk in graph.stream(initial_state):
    # chunk[0] = {'clarify': {...}}  # 正常收到
    # chunk[1] = {'search_plan': {...}}  # 挂死在这里
```

### 问题原因推测

uvicorn 在 macOS 上使用默认的 `asyncio` event loop 配置。当 `graph.stream()` 执行时（中间经过 LangChain/LangGraph 的异步调度），线程阻塞导致死锁。

关键证据：
- LLM 调用本身（`llm.invoke()`）在 server 里正常（`/llm-test` 4.8s 返回）
- 但 `graph.stream()` 在 node 间切换时挂死
- 怀疑是 LangGraph 内部状态管理与 uvicorn event loop 的兼容性问题

### 尝试的修复方案

| 方案 | 代码位置 | 结果 | 失败原因 |
|------|---------|------|----------|
| `asyncio.create_task` | `create_task` handler | 静默失败 | 没有 active event loop |
| `ThreadPoolExecutor.submit()` + 新 loop | `_run_graph_sync_wrapper` | **信号量崩溃** | `signal` 仅在主线程有效 |
| `asyncio.to_thread()` | `_run_graph` 内 | **挂死** | 仍触发相同死锁 |
| `asyncio.get_running_loop().run_in_executor()` | `_run_graph` | **挂死** | executor 内调用 `run_in_executor` 死锁 |

### 当前代码状态

**`_run_graph_sync_wrapper`（当前实现）：**
- 直接调用 `_run_graph_sync()`（纯同步版本）
- 在 `_bg_executor` 线程池线程中执行
- **存在死锁问题，尚未修复**

**`_run_graph`（async 版本）：**
- 使用 `asyncio.to_thread()` 调度
- **存在死锁问题，尚未修复**

---

## 汇总：问题修复状态

### ✅ 已修复并验证通过

| # | Issue | 文件 | 验证结果 |
|---|-------|------|----------|
| 1 | ClarifyAgent LLM prompt 保守 | `src/research/prompts/clarify_prompt.py` + `src/research/policies/clarify_policy.py` | ✅ 端到端通过（2次测试）|
| 2 | 后台任务执行图挂死（P0） | `src/api/routes/tasks.py` | ✅ Codex 修复，测试通过 |
| 3 | `TaskRecord` 缺少 `review_feedback` 字段 | `src/models/task.py` | ✅ `review_feedback=True`, `review_passed=True` |
| 4 | `_run_graph` 未同步 review 结果 | `src/api/routes/tasks.py` | ✅ Review 数据正确同步 |
| 5 | `SkillRunRequest.inputs` 类型错误 | `src/models/skills.py` | ✅ 早期已修复 |

### 验证测试记录（2026-04-11）

```bash
# 测试1：简单 topic
POST {"input_value":"调研RAG", "source_type":"research"}
→ status=completed, needs_followup=False, confidence=0.68
→ topic=RAG, desired_output=survey_outline
→ search_plan=present, review_passed=True

# 测试2：长 topic
POST {"input_value":"多模态大模型在医学影像诊断的应用", "source_type":"research"}
→ status=completed, needs_followup=False, confidence=0.68
→ topic=多模态大模型在医学影像诊断的应用
→ desired_output=survey_outline, search_plan=present
```

---

## Codex 修复（已实施并验证）

Codex 对 `src/api/routes/tasks.py` 的修复已实施并通过验证：
- 解决了 uvicorn 上下文中 `graph.stream()` 挂死的 asyncio 兼容性问题
- 简化了 `_bg_executor.submit()` 的调用方式
- 端到端测试通过（见上方验证记录）

具体代码变更见 git diff。

---

## 调试过程记录（可供回溯）

### 调试文件位置
- Debug 日志：`/tmp/uvicorn_debug.txt`（如需复现）
- Backend 进程：端口 `8000`（uvicorn）
- 前端进程：端口 `5173`（Vite）

### 关键测试命令

```bash
# 重启后端
cd /Users/artorias/devpro/PaperReader_agent
lsof -ti:8000 | xargs kill -9
/opt/homebrew/anaconda3/bin/python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 &

# 提交测试任务
curl -s -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"input_type":"research","input_value":"调研RAG","source_type":"research","report_mode":"draft"}'

# 查看结果（等待 15s 后）
sleep 15 && curl -s http://localhost:8000/tasks/{task_id}

# 测试 LLM（在 server 内）
curl -s http://localhost:8000/tasks/llm-test

# 测试 graph（在 server 内）
curl -s http://localhost:8000/tasks/graph-test

# 测试 policy fallback（独立测试）
cd /Users/artorias/devpro/PaperReader_agent
/opt/homebrew/anaconda3/bin/python -c "
from src.research.policies.clarify_policy import to_limited_brief
b = to_limited_brief('调研RAG')
print(f'needs_followup={b.needs_followup}, confidence={b.confidence}')
"
```

### 环境信息
- OS：macOS Darwin 24.6.0
- Python：3.12（Anaconda）
- 后端框架：FastAPI + Uvicorn
- LLM Provider：DeepSeek（API Key 已配置）
- 数据库：PostgreSQL（`paperreader`）+ Milvus

## 1. ClarifyAgent 在整个系统里的定位

它不是聊天 agent，也不是工具 agent。
 它的唯一职责是：

把用户原始 research request 转成结构化 ResearchBrief。

也就是说，它做的是：

- 识别研究主题
- 识别用户真正目标
- 补全或显式暴露歧义
- 约束范围
- 产出可执行的研究 brief

所以它更像一个：

Schema-bound Clarification Agent

而不是：

- ReAct agent
- Plan-Execute agent
- Tool-using agent

这么定有两个原因。

第一，你当前仓库的强项是 StateGraph、typed state、Pydantic/schema design，而不是自由规划和工具运行时；当前 planning 还偏弱，tool runtime 也没有统一起来。Clarify 这一步恰好可以完全避开这些弱项，走“固定节点 + 强结构化输出”的路线。

第二，repo 总结里已经明确指出当前 structured output“已有 JSON 输出约束和 Pydantic model，但还不够硬”，建议优先走 provider-native structured output 或严格的 Pydantic binding。ClarifyAgent 正是最适合先落地这一建议的节点。

------

## 2. ClarifyAgent 适合的架构

我建议它用下面这套最稳的架构：

StateGraph 节点 + Agent Service + Strict Schema + Fallback Policy

也就是四层：

### 第一层：Graph Node

比如：

- src/research/graph/nodes/clarify.py

作用：

- 从 ResearchState 取输入
- 调 ClarifyAgentService
- 回填 brief / warnings / ambiguity flags
- 发 node 级事件

### 第二层：Agent Service

比如：

- src/research/agents/clarify_agent.py

作用：

- 组 prompt
- 调模型
- 解析结构化输出
- 做字段修复/默认值填充
- 返回 ResearchBrief

### 第三层：Schema

比如：

- src/models/research.py

定义：

- ClarifyInput
- ResearchBrief
- AmbiguityItem
- ClarifyDiagnostics

### 第四层：Policy / Fallback

比如：

- src/research/policies/clarify_policy.py

作用：

- 判断是否需要澄清补问
- 判断是否可继续下游 search_plan
- 判断是否安全中止 / limited mode

这套架构的优点是：

- 不把 prompt、schema、graph、fallback 混在一起
- 非常适合你当前仓库“固定图主线”的演进方式
- 后面如果 provider 换了，不会把 graph 节点炸掉
- 测试也最好写

------

## 3. ClarifyAgent 的核心功能，不要做多

这一阶段它只做 5 件事。

### 功能 1：解析 research intent

输入一句模糊 query，比如：

> 最近多模态医学报告生成方向有哪些可借鉴方法？

ClarifyAgent 要先识别：

- 主题是什么
- 用户想要什么类型的产出
- 调研目标是综述、baseline、related work，还是选题前探索

这一步输出到：

- topic
- goal
- desired_output

### 功能 2：提取约束条件

比如用户可能隐含了：

- 时间范围
- 领域范围
- 只关心某类数据
- 想看方法总结还是工程落地

输出到：

- time_range
- domain_scope
- source_constraints
- focus_dimensions

### 功能 3：拆分子问题

比如上面的 query，拆完后可能是：

- 多模态医学报告生成有哪些主流方法路线
- 哪些工作使用视觉+文本联合建模
- 哪些工作和 segmentation / grounding 更相关
- 哪些方法适合作为可复现实验 baseline

输出到：

- sub_questions: list[str]

### 功能 4：识别歧义并显式标注

不是所有 query 都够清楚。
 ClarifyAgent 要做的一件关键事，是别假装自己全懂，而是要把歧义产物化。

比如：

- “最近”是近两年还是近五年
- “可借鉴方法”是要科研灵感还是工程可复现 baseline
- “多模态医学报告生成”是影像报告还是通用医学 VLM

输出到：

- ambiguities
- needs_followup: bool

### 功能 5：生成可传递给下游的标准 brief

最终不是输出一段自然语言，而是一个固定结构：

- topic
- goal
- sub_questions
- constraints
- desired_output
- ambiguities
- confidence

这就是给 SearchPlanAgent 的输入。

------

## 4. ClarifyAgent 不该做什么

这一步要强行克制，别一开始就做过头。

它不应该：

- 直接检索论文
- 直接调用 MCP 外部工具
- 直接读 PDF
- 直接生成综述
- 直接做多 agent 协作

原因很简单：
 当前仓库工具运行时还没统一，MCP 还是短板；planning 也没有显式 node。ClarifyAgent 应该先作为“planning 入口”稳定下来，而不是自己变成一个全能 agent。

------

## 5. 推荐的 schema 设计

这一部分要定死，不然后面会漂。

### ClarifyInput

```python
class ClarifyInput(BaseModel):
    raw_query: str
    workspace_context: str | None = None
    uploaded_source_ids: list[str] = []
    preferred_output: str | None = None
```

### AmbiguityItem

```python
class AmbiguityItem(BaseModel):
    field: str
    reason: str
    suggested_options: list[str] = []
```

### ResearchBrief

```python
class ResearchBrief(BaseModel):
    topic: str
    goal: str
    desired_output: str
    sub_questions: list[str]
    time_range: str | None = None
    domain_scope: str | None = None
    source_constraints: list[str] = []
    focus_dimensions: list[str] = []
    ambiguities: list[AmbiguityItem] = []
    needs_followup: bool = False
    confidence: float = 0.0
    schema_version: str = "v1"
```

### ClarifyResult

```python
class ClarifyResult(BaseModel):
    brief: ResearchBrief
    warnings: list[str] = []
    raw_model_output: str | None = None
```

这里我建议你一开始就把 schema_version 带上。
 repo 总结里专门点了“当前 structured output 没有 schema version”，后面会影响演进。Clarify 这里最适合先补掉。

------

## 6. ClarifyAgent 的内部执行流程

它的 service 内部建议就是 4 步。

### 第一步：输入标准化

把用户输入先做轻度清洗：

- 去首尾空白
- 裁剪长度
- 标准化空字段
- 合并 workspace context

### 第二步：结构化提示

不要让模型自由发挥，prompt 要明确要求：

- 不回答研究内容本身
- 只做需求澄清
- 只返回 schema
- 不足信息要写入 ambiguities
- 不得臆造具体论文结论

### 第三步：严格解析

优先顺序应该是：

1. provider-native structured output
2. Pydantic schema binding
3. JSON parse + strict repair
4. fallback limited brief

repo 里现在还是 prompt + json.loads() 为主，这不够硬。ClarifyAgent 这里建议你直接把“强 schema”作为第一原则。

### 第四步：结果校验与降级

最少做这些校验：

- topic 非空
- goal 非空
- desired_output 非空
- sub_questions 至少 1 条
- confidence 范围在 0–1

如果不满足：

- 记录 warning
- 尝试一次 repair
- 还不行就输出 needs_followup=True 的 limited brief

这样和你当前 repo 的 limited / safe_abort / abstained 风格也一致。

------

## 7. 这个 agent 最适合的“范式”

我给你一个明确结论：

### 最推荐

Structured Output + Fixed Node

这是 ClarifyAgent 的主范式。

### 不推荐

ReAct
 因为 Clarify 阶段没有必要思考“该调哪个工具”。

### 也不推荐

Plan-Execute
 因为 Clarify 本身就是 planning 的前置阶段，它不需要再做复杂执行规划。

### 可选增强

Self-check / Validator pass
 也就是 first pass 生成 brief，second pass 只做字段校验和补洞。

这个增强很适合你后面做稳定性优化，但不是 Phase 1 第一优先级。

------

## 8. 代码文件应该怎么落

建议直接落成这些文件：

```text
src/
  models/
    research.py
  research/
    agents/
      clarify_agent.py
    graph/
      nodes/
        clarify.py
    prompts/
      clarify_prompt.py
    policies/
      clarify_policy.py
```

### clarify_agent.py

核心类：

- ClarifyAgentService

公开方法：

- run(input: ClarifyInput) -> ClarifyResult

### clarify.py

核心函数：

- run_clarify_node(state: ResearchState) -> dict

它做的事情：

- 从 state 取 raw_query
- 调 agent service
- 回填 brief
- 更新 node_status
- 发 SSE 事件

### clarify_prompt.py

不要把 prompt 字符串写死在 service 里。
 拆出来，后面迭代才好做 diff / eval。

### clarify_policy.py

专门放规则：

- should_request_followup(brief)
- is_brief_valid(brief)
- to_limited_brief(raw_query)

------

## 9. 节点输入输出契约

### 输入 state

```python
{
  "task_id": "...",
  "workspace_id": "...",
  "user_input": {
    "query": "...",
    "preferred_output": "...",
    "source_ids": [...]
  },
  "warnings": [],
  "error": None
}
```

### 输出 patch

```python
{
  "brief": ResearchBrief(...),
  "warnings": [...],
  "current_stage": "clarify"
}
```

不要在这个节点里直接改太多状态。
 Clarify 节点只应该写：

- brief
- warnings
- current_stage
- 可选 followup_required

------

## 10. 测试怎么写

ClarifyAgent 很适合先把测试打稳。

至少写三类：

### 1. 正常输入

输入比较清晰：

- 能正常产出 brief
- needs_followup=False

### 2. 模糊输入

比如：

- “帮我看看最近有什么好方法”

预期：

- ambiguities 不为空
- needs_followup=True

### 3. 结构化输出失败

模拟 LLM 返回坏 JSON / 缺字段

预期：

- 进入 repair 或 limited brief
- 有 warning
- 节点不直接崩

repo 现在整体测试基础不差，pytest 已通过很多用例，但 eval 和 trace 还没闭环，所以 ClarifyAgent 最适合先把单元测试和节点测试做好。

------

## 11. 一个最小实现流程

你现在真开工的话，按这个顺序最稳：

### 第一步

先写 ResearchBrief / ClarifyInput / ClarifyResult

### 第二步

写 clarify_prompt.py

### 第三步

写 ClarifyAgentService.run()

### 第四步

写 clarify_policy.py

### 第五步

把它接成 clarify graph node

### 第六步

补：

- /tasks/{id} 返回 brief
- SSE 里加 node_started / node_finished

这条线最短，也最不会返工。

------

## 12. 简要流图

先用这个就够：

flowchart TD    A[User Query / Task Input] --> B[Clarify Node]    B --> C[ClarifyAgentService]    C --> D[LLM Structured Output]    D --> E[Schema Validation / Repair]    E --> F[ResearchBrief]    F --> G[Persist to State]    G --> H[Workspace Artifact]    G --> I[SSE / Task Status]

------


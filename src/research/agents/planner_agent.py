"""PlannerAgent — Plan-and-Execute 模式。

设计模式说明：
- Plan-and-Execute：先规划（生成完整执行计划），再执行。
- 核心思想：LLM 先全面规划，然后由执行器按序执行，降低单步决策错误累积。
- 适用场景：复杂多步骤任务，如本研究调研。

与 ReAct 的区别：
- ReAct：每步推理后立即执行，再观察，再推理（紧密交织）
- Plan-and-Execute：先一次性规划完整路径，再逐一执行（松耦合）

阶段划分：
  Phase 1 (Plan):   LLM 一次性生成完整 SearchPlan（含所有 query_groups）
  Phase 2 (Execute): 执行器按 plan 执行，每步结果记录到 memory
  Phase 3 (Validate): 验证 plan 执行结果是否满足初始目标
"""

from __future__ import annotations

import logging
from typing import Any
from typing import TypedDict

from langgraph.graph import START, StateGraph
from src.memory.manager import get_memory_manager

logger = logging.getLogger(__name__)


# ─── Prompt Templates ───────────────────────────────────────────────────────


PLAN_PHASE_PROMPT = """你是一个研究规划专家（Research Planner）。

给定以下 ResearchBrief，请一次性生成完整的多阶段 SearchPlan。

**输出要求（严格 JSON）：**
```json
{{
  "plan_goal": "本轮搜索的核心目标（1 句话）",
  "query_groups": [
    {{
      "group_id": "探索阶段",
      "queries": ["查询1", "查询2", "..."],
      "intent": "exploration",
      "priority": 1,
      "expected_hits": 20,
      "notes": "探索方向说明"
    }},
    {{
      "group_id": "精化阶段",
      "queries": ["查询1", "查询2", "..."],
      "intent": "refinement",
      "priority": 2,
      "expected_hits": 15,
      "notes": "精化方向说明"
    }},
    {{
      "group_id": "验证阶段",
      "queries": ["查询1", "..."],
      "intent": "validation",
      "priority": 3,
      "expected_hits": 10,
      "notes": "验证方向说明"
    }}
  ],
  "source_preferences": ["arxiv", "semantic_scholar"],
  "coverage_notes": "本计划的预期覆盖说明"
}}
```

规则：
- query_groups 数量：2-4 个，不要超过 4 个
- 每个 query 长度：5-15 个词，不要太长
- 必须覆盖：研究主题 + 方法 + 数据集 + 应用
- expected_hits 是预期返回数量，不是必须达到
"""

EXECUTE_PHASE_SYSTEM = """你是一个执行验证专家（Executor Validator）。

给定原始 ResearchBrief、生成的 SearchPlan，以及当前的执行结果，
请判断：
1. 当前进度是否满足计划目标
2. 是否需要调整后续查询
3. 是否应该停止

输出（严格 JSON）：
```json
{{
  "status": "on_track | deviation | complete | stuck",
  "current_coverage": "当前覆盖说明",
  "adjustments": ["调整1", "调整2"],
  "should_stop": true或false,
  "stop_reason": "停止原因（如有）"
}}
```
"""


# ─── PlannerAgent ──────────────────────────────────────────────────────────


class PlanAndExecutePhase:
    """单个执行阶段。"""

    def __init__(self, group_id: str, queries: list[str], intent: str, priority: int, expected_hits: int):
        self.group_id = group_id
        self.queries = queries
        self.intent = intent
        self.priority = priority
        self.expected_hits = expected_hits
        self.executed_queries: list[str] = []
        self.query_results: list[dict] = []
        self.completed = False

    def mark_executed(self, query: str, result: dict) -> None:
        self.executed_queries.append(query)
        self.query_results.append(result)
        if len(self.executed_queries) >= len(self.queries):
            self.completed = True


class PlannerGraphState(TypedDict, total=False):
    brief: dict[str, Any]
    warnings: list[str]
    plan: Any
    phases: list[PlanAndExecutePhase]
    search_plan: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    execution_log: list[dict[str, Any]]
    execution_results: dict[str, Any]
    validation: dict[str, Any]


class PlannerAgent:
    """
    Plan-and-Execute 模式的 Planner Agent。

    工作流程：
      ┌─────────────┐
      │  PLAN PHASE │  LLM 一次性生成完整 SearchPlan
      └──────┬──────┘
             │  SearchPlan
             ▼
      ┌─────────────┐
      │ EXECUTE LOOP │  按 priority 顺序执行每个 query_group
      │  Phase 1..N   │  每步记录结果到 memory
      └──────┬──────┘
             │  execution_results
             ▼
      ┌─────────────┐
      │ VALIDATE     │  LLM 验证执行结果是否满足目标
      └──────┬──────┘
             │  final_plan + validation_report
    """

    def __init__(self, workspace_id: str | None = None, task_id: str | None = None):
        self.workspace_id = workspace_id
        self.task_id = task_id
        self.mm = get_memory_manager(workspace_id) if workspace_id else None

    # ── Plan Phase ──────────────────────────────────────────────────────────

    def plan_phase(self, brief: dict) -> dict[str, Any]:
        """
        PLAN PHASE：LLM 一次性生成完整多阶段执行计划。

        与 SearchPlanAgent 的区别：
        - SearchPlanAgent：边推理边执行（ReAct）
        - PlannerAgent.plan_phase()：一次性生成所有阶段，再执行
        """
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from src.models.research import SearchPlan
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=8192)

        brief_text = self._serialize_brief(brief)
        memory_context = ""
        if self.mm:
            try:
                topic = brief.get("research_topic") or brief.get("topic", "")
                memory_context = self.mm.build_context(topic=topic, max_semantic=3, max_episodes=3)
            except Exception:
                pass

        user_prompt = f"""## ResearchBrief

{brief_text}

## 历史记忆（参考）

{memory_context or '（无）'}

请根据以上信息，生成完整的多阶段搜索计划。"""

        try:
            resp = llm.invoke([
                SystemMessage(content=PLAN_PHASE_PROMPT),
                HumanMessage(content=user_prompt),
            ])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            plan_data = self._parse_json(raw)

            if plan_data:
                plan = SearchPlan.model_validate(plan_data)
                self._store_plan_memory(plan, brief)
                return {
                    "plan": plan,
                    "phases": self._build_phases(plan),
                    "phase": "plan",
                    "plan_summary": plan.plan_goal,
                }
        except Exception as exc:
            logger.exception("[PlannerAgent.plan_phase] failed: %s", exc)

        # Fallback
        from src.research.policies.search_plan_policy import to_fallback_plan

        plan = to_fallback_plan(brief)
        return {
            "plan": plan,
            "phases": self._build_phases(plan),
            "phase": "plan",
            "plan_summary": plan.plan_goal,
            "warnings": ["LLM 规划失败，使用 fallback plan"],
        }

    # ── Execute Phase ─────────────────────────────────────────────────────

    def execute_phase(self, phases: list[PlanAndExecutePhase]) -> dict[str, Any]:
        """
        EXECUTE PHASE：按 priority 顺序执行每个阶段的 queries。

        Plan-and-Execute 的关键设计：
        - 按阶段批量执行，而非逐条执行（提高效率）
        - 每个阶段执行完毕后才进入下一阶段（保持阶段边界）
        - 阶段之间可记录 memory，供 validate 使用
        """
        from src.tools.search_tools import _searxng_search

        all_candidates: list[dict] = []
        seen_urls: set[str] = set()
        execution_log: list[dict] = []

        for phase in phases:
            if phase.completed:
                continue

            logger.info("[PlannerAgent.execute] phase=%s, queries=%d", phase.group_id, len(phase.queries))

            # SensoryMemory: 记录阶段开始
            if self.mm:
                self.mm.add_sensory(
                    "phase_start",
                    {"phase": phase.group_id, "intent": phase.intent, "query_count": len(phase.queries)},
                )

            for query in phase.queries:
                if query in phase.executed_queries:
                    continue

                try:
                    result = _searxng_search(query, engines="arxiv", max_results=20)
                    if result.get("ok"):
                        hits = result.get("hits", [])
                        phase.mark_executed(query, result)

                        for hit in hits:
                            url = hit.get("url", "")
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                all_candidates.append({
                                    "title": hit.get("title", ""),
                                    "url": url,
                                    "abstract": hit.get("content", "")[:500],
                                    "engine": hit.get("engine", "arxiv"),
                                    "published_date": hit.get("publishedDate"),
                                    "query": query,
                                    "phase": phase.group_id,
                                    "intent": phase.intent,
                                })
                    else:
                        phase.mark_executed(query, {"ok": False, "error": result.get("error", "")})

                    # SensoryMemory: 记录每条查询结果
                    if self.mm:
                        self.mm.add_tool_output("searxng", {"query": query, "result": result})

                except Exception as exc:
                    logger.warning("[PlannerAgent.execute] query '%s' failed: %s", query, exc)
                    phase.mark_executed(query, {"ok": False, "error": str(exc)})

            # 每个阶段完成后记录 SemanticMemory
            if self.mm:
                self.mm.add_semantic(
                    f"完成搜索阶段: {phase.group_id}，intent={phase.intent}，queries={len(phase.executed_queries)}",
                    memory_type="research_fact",
                    metadata={"source": "planner_agent", "workspace_id": self.workspace_id},
                )

            execution_log.append({
                "phase": phase.group_id,
                "intent": phase.intent,
                "executed": len(phase.executed_queries),
                "total": len(phase.queries),
                "candidates_from_phase": len([c for c in all_candidates if c.get("phase") == phase.group_id]),
            })

        return {
            "candidates": all_candidates,
            "execution_log": execution_log,
            "phase": "execute",
        }

    # ── Validate Phase ─────────────────────────────────────────────────────

    def validate_phase(self, brief: dict, plan: Any, execution_results: dict) -> dict[str, Any]:
        """
        VALIDATE PHASE：LLM 验证执行结果是否满足计划目标。

        Plan-and-Execute 的最后一步：
        - ReAct 无此步骤（每步即验证）
        - 这里显式验证：给 LLM 完整上下文做全局判断
        """
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=2048)

        brief_text = self._serialize_brief(brief)
        plan_goal = plan.plan_goal if hasattr(plan, "plan_goal") else str(plan)
        execution_summary = self._summarize_execution(execution_results)

        user_prompt = f"""## ResearchBrief

{brief_text}

## SearchPlan 目标

{plan_goal}

## 执行结果摘要

{execution_summary}

请验证执行结果是否满足 SearchPlan 目标。"""

        try:
            resp = llm.invoke([
                SystemMessage(content=EXECUTE_PHASE_SYSTEM),
                HumanMessage(content=user_prompt),
            ])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            validation = self._parse_json(raw) or {}

            return {
                "phase": "validate",
                "validation": validation,
                "candidates": execution_results.get("candidates", []),
                "execution_log": execution_results.get("execution_log", []),
            }
        except Exception as exc:
            logger.warning("[PlannerAgent.validate_phase] failed: %s", exc)
            return {
                "phase": "validate",
                "validation": {"status": "unknown", "error": str(exc)},
                "candidates": execution_results.get("candidates", []),
                "execution_log": execution_results.get("execution_log", []),
            }

    # ── 完整 Pipeline ─────────────────────────────────────────────────────

    def run(self, brief: dict) -> dict[str, Any]:
        """
        完整 Plan-and-Execute Pipeline。

        流程：plan_phase → execute_phase → validate_phase
        """
        logger.info("[PlannerAgent] Starting Plan-and-Execute pipeline via LangGraph")
        result = self.build_graph().invoke({"brief": brief, "warnings": []})
        candidates = list(result.get("candidates", []))
        return {
            "search_plan": result.get("search_plan"),
            "candidates": candidates,
            "execution_log": list(result.get("execution_log", [])),
            "validation": result.get("validation", {}),
            "paradigm": "plan_and_execute",
            "summary": f"Plan-and-Execute 完成：{len(candidates)} 篇候选论文",
            "planner_warnings": list(result.get("warnings", [])),
        }

    # ── Helpers ────────────────────────────────────────────────────────────

    def _build_phases(self, plan: Any) -> list[PlanAndExecutePhase]:
        """从 SearchPlan 构建可执行的阶段列表。"""
        phases = []
        for g in plan.query_groups:
            phase = PlanAndExecutePhase(
                group_id=g.group_id,
                queries=list(g.queries),
                intent=g.intent,
                priority=g.priority,
                expected_hits=g.expected_hits,
            )
            phases.append(phase)
        # 按 priority 排序
        phases.sort(key=lambda p: p.priority)
        return phases

    def _serialize_brief(self, brief: dict) -> str:
        import json

        topic = brief.get("research_topic") or brief.get("topic", "")
        goal = brief.get("goal", "")
        sub_qs = brief.get("sub_questions", [])
        output = brief.get("desired_output", "")
        return f"Topic: {topic}\nGoal: {goal}\nSub-questions: {json.dumps(sub_qs, ensure_ascii=False)}\nDesired output: {output}"

    def _store_plan_memory(self, plan: Any, brief: dict) -> None:
        if not self.mm:
            return
        try:
            topic = brief.get("research_topic") or brief.get("topic", "")
            self.mm.add_semantic(
                f"SearchPlan: {plan.plan_goal}",
                memory_type="research_fact",
                metadata={
                    "source": "planner_agent",
                    "group_count": len(plan.query_groups),
                    "workspace_id": self.workspace_id,
                },
            )
        except Exception as exc:
            logger.warning("[PlannerAgent] Failed to store plan memory: %s", exc)

    def _summarize_execution(self, results: dict) -> str:
        candidates = results.get("candidates", [])
        log = results.get("execution_log", [])
        total = len(candidates)
        lines = [f"总候选论文数：{total}", f"执行阶段数：{len(log)}"]
        for entry in log:
            lines.append(f"  - {entry['phase']} ({entry['intent']}): {entry['executed']}/{entry['total']} queries, {entry['candidates_from_phase']} candidates")
        return "\n".join(lines)

    def _parse_json(self, text: str) -> dict | None:
        import json

        text = text.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def build_graph(self):
        workflow = StateGraph(PlannerGraphState)
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("execute", self._execute_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_edge(START, "plan")
        workflow.add_edge("plan", "execute")
        workflow.add_edge("execute", "validate")
        return workflow.compile()

    def _plan_node(self, state: PlannerGraphState) -> dict[str, Any]:
        result = self.plan_phase(state.get("brief") or {})
        plan = result.get("plan")
        warnings = list(state.get("warnings", []))
        warnings.extend(result.get("warnings", []))
        return {
            "plan": plan,
            "phases": list(result.get("phases", [])),
            "search_plan": plan.model_dump(mode="json") if hasattr(plan, "model_dump") else plan,
            "warnings": warnings,
        }

    def _execute_node(self, state: PlannerGraphState) -> dict[str, Any]:
        phases = list(state.get("phases", []))
        result = self.execute_phase(phases)
        return {
            "execution_results": result,
            "candidates": list(result.get("candidates", [])),
            "execution_log": list(result.get("execution_log", [])),
        }

    def _validate_node(self, state: PlannerGraphState) -> dict[str, Any]:
        plan = state.get("plan")
        execution_results = state.get("execution_results") or {
            "candidates": state.get("candidates", []),
            "execution_log": state.get("execution_log", []),
        }
        if plan is None:
            warnings = list(state.get("warnings", []))
            warnings.append("Planner graph reached validation without a plan.")
            return {"validation": {"status": "missing_plan"}, "warnings": warnings}

        result = self.validate_phase(state.get("brief") or {}, plan, execution_results)
        return {
            "validation": result.get("validation", {}),
            "candidates": list(result.get("candidates", [])),
            "execution_log": list(result.get("execution_log", [])),
        }


# ─── 入口函数 ───────────────────────────────────────────────────────────────


def run_planner_agent(state: dict, inputs: dict) -> dict:
    """PlannerAgent 入口（兼容 supervisor 格式）。"""
    workspace_id = inputs.get("workspace_id") or state.get("workspace_id")
    task_id = inputs.get("task_id") or state.get("task_id")
    brief = state.get("brief") or inputs.get("brief", {})

    agent = PlannerAgent(workspace_id=workspace_id, task_id=task_id)
    try:
        return agent.run(brief=brief)
    except Exception as exc:
        logger.exception("[PlannerAgent] run failed: %s", exc)
        return {
            "search_plan": None,
            "candidates": [],
            "paradigm": "plan_and_execute",
            "planner_warnings": [f"PlannerAgent failed: {exc}"],
        }


def plan_search(state: dict, inputs: dict) -> dict:
    """兼容别名。"""
    return run_planner_agent(state, inputs)

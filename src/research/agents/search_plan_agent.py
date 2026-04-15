"""SearchPlanAgent — 真实 Agent 循环：工具调用 + 工作记忆 + 反思 + 有界迭代。"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm import build_chat_llm
from src.agent.report_frame import extract_json_block, extract_llm_text
from src.agent.settings import Settings
from src.models.research import (
    SearchPlan,
    SearchPlannerMemory,
    SearchPlanResult,
)
from src.research.policies.search_plan_policy import should_stop, to_fallback_plan
from src.research.prompts.search_plan_prompt import (
    FEW_SHOT_EXAMPLES,
    SEARCHPLAN_SYSTEM_PROMPT,
    build_reflection_prompt,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10


def _emit_progress(emit_progress: Callable[[str], None] | None, message: str) -> None:
    if emit_progress:
        emit_progress(message)


def _parse_json(text: str) -> dict | None:
    try:
        raw = extract_json_block(text)
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _validate_plan(data: dict) -> SearchPlan | None:
    try:
        return SearchPlan.model_validate(data)
    except Exception:
        return None


def _invoke_llm(
    settings: Settings,
    system_content: str,
    few_shot: str,
    user_content: str,
    max_tokens: int = 8192,
) -> str:
    llm = build_chat_llm(settings, max_tokens=max_tokens)
    messages = [
        SystemMessage(content=system_content),
        SystemMessage(content=few_shot),
        HumanMessage(content=user_content),
    ]
    resp = llm.invoke(messages)
    return extract_llm_text(resp)


# ─── 工具调用（按类型分组）────────────────────────────────────────────────────


def _call_search_arxiv(query: str, top_k: int = 10) -> dict[str, Any]:
    """调用 search_arxiv 工具，返回原始结果 dict。"""
    from src.tools.search_tools import search_arxiv as _fn

    try:
        return {"ok": True, "result": _fn.invoke({"query": query, "top_k": top_k})}
    except Exception as exc:
        logger.warning("search_arxiv failed for '%s': %s", query, exc)
        return {"ok": False, "error": str(exc)}


def _call_expand_keywords(topic: str, focus: str = "methods") -> dict[str, Any]:
    from src.tools.search_tools import expand_keywords as _fn

    try:
        return {"ok": True, "result": _fn.invoke({"topic": topic, "focus_dimension": focus})}
    except Exception as exc:
        logger.warning("expand_keywords failed for '%s': %s", topic, exc)
        return {"ok": False, "error": str(exc)}


def _call_summarize_hits(results: str) -> dict[str, Any]:
    from src.tools.search_tools import summarize_hits as _fn

    try:
        return {"ok": True, "result": _fn.invoke({"results": results})}
    except Exception as exc:
        logger.warning("summarize_hits failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _call_detect_noise(results: str) -> dict[str, Any]:
    from src.tools.search_tools import detect_sparse_or_noisy_queries as _fn

    try:
        return {"ok": True, "result": _fn.invoke({"results": results})}
    except Exception as exc:
        logger.warning("detect_sparse_or_noisy_queries failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _count_results(result_str: str) -> int:
    """从工具输出字符串中估算命中数量。"""
    lines = result_str.strip().split("\n")
    count = sum(1 for l in lines if l.startswith("[") and "] " in l)
    return count


# ─── Agent Loop ────────────────────────────────────────────────────────────────


def run(
    brief: dict[str, Any],
    emit_progress: Callable[[str], None] | None = None,
) -> SearchPlanResult:
    """SearchPlanAgent 主入口：真实 Agent 循环。

    流程：初始化 → 工具观察 → 记忆更新 → 反思 → 修订/停止
    """
    settings = Settings.from_env()
    memory = SearchPlannerMemory()
    raw_output: str | None = None
    warnings: list[str] = []
    plan: SearchPlan | None = None
    current_results: str = ""

    # ── 初始化阶段：生成初始查询列表 ────────────────────────────────────────
    brief_str = json.dumps(brief, ensure_ascii=False, indent=2)
    topic = brief.get("research_topic") or brief.get("topic", "")
    sub_questions = brief.get("sub_questions", [])

    memory.iteration_count = 0
    memory.remaining_budget = MAX_ITERATIONS

    # Step 1：扩展关键词（如果 agent 可用 LLM）
    expanded_kw = []
    _emit_progress(emit_progress, "Initializing search planning from research brief.")
    try:
        _emit_progress(emit_progress, "Expanding topic keywords for first-pass retrieval.")
        kw_result = _call_expand_keywords(topic, "methods")
        if kw_result["ok"]:
            expanded_kw = [l.strip("- ").strip() for l in kw_result["result"].split("\n") if l.strip()]
            memory.planner_reflections.append(f"关键词扩展得到 {len(expanded_kw)} 个候选词")
            _emit_progress(emit_progress, f"Keyword expansion produced {len(expanded_kw)} candidate phrases.")
    except Exception as exc:
        warnings.append(f"关键词扩展失败：{exc}，使用原始关键词继续")
        _emit_progress(emit_progress, f"Keyword expansion failed: {exc}. Continuing with raw topic.")

    # ── Agent Loop ────────────────────────────────────────────────────────────
    for iteration in range(1, MAX_ITERATIONS + 1):
        memory.iteration_count = iteration
        memory.remaining_budget -= 1
        _emit_progress(
            emit_progress,
            f"Iteration {iteration}: planning with {len(memory.attempted_queries)} attempted queries so far.",
        )

        # ── Stop check（每次迭代开始前）───────────────────────────────────
        if plan is not None:
            stop, stop_reason = should_stop(memory, plan)
            if stop:
                memory.last_action = f"stop: {stop_reason}"
                logger.info("SearchPlanAgent stopping: %s", stop_reason)
                break

        # ── Observe：调用搜索工具 ──────────────────────────────────────────
        queries_to_try = _propose_queries(iteration, topic, expanded_kw, memory)
        iteration_results = []
        _emit_progress(
            emit_progress,
            f"Iteration {iteration}: searching {len(queries_to_try)} queries in arXiv/SearXNG toolchain.",
        )

        for q in queries_to_try:
            if q in memory.attempted_queries:
                continue  # 避免重复查询
            memory.attempted_queries.append(q)

            res = _call_search_arxiv(q, top_k=10)
            if res["ok"]:
                raw_result = res["result"]
                iteration_results.append(raw_result)
                hit_count = _count_results(raw_result)
                memory.query_to_hits[q] = hit_count
                if hit_count == 0:
                    memory.empty_queries.append(q)
                current_results += raw_result + "\n\n"
            else:
                memory.planner_reflections.append(f"查询 '{q}' 失败：{res.get('error')}")

        if not iteration_results:
            memory.last_action = "no_results"
            _emit_progress(emit_progress, f"Iteration {iteration}: no usable search results, continuing.")
            continue

        # ── Reflect：调用分析工具 ─────────────────────────────────────────
        try:
            _emit_progress(emit_progress, f"Iteration {iteration}: summarizing current hits and checking noise.")
            # 摘要分析
            sum_result = _call_summarize_hits(current_results)
            if sum_result["ok"]:
                memory.planner_reflections.append(
                    f"迭代 {iteration} 摘要：{sum_result['result'][:200]}"
                )

            # 噪声检测
            noise_result = _call_detect_noise(current_results)
            if noise_result["ok"]:
                text = noise_result["result"]
                # 提取噪声查询（格式："- noisy_query"）
                for line in text.split("\n"):
                    if "noisy" in line.lower() or "sparse" in line.lower():
                        memory.high_noise_queries.append(line.strip())
        except Exception as exc:
            memory.planner_reflections.append(f"反思阶段异常：{exc}")
            _emit_progress(emit_progress, f"Iteration {iteration}: reflection tools raised {exc}.")

        # ── Plan generation：LLM 综合当前状态生成 SearchPlan ──────────────
        memory_dict = memory.model_dump()
        reflection_prompt = build_reflection_prompt(memory_dict)

        user_prompt = f"""\
## ResearchBrief

{brief_str}

## 当前搜索记忆

{reflection_prompt}

## 当前搜索结果摘要

{current_results[:3000] if current_results else "（暂无结果）"}

请基于以上信息，生成最优的 SearchPlan JSON。
如果当前覆盖已充分，使用 STOP 决策。
如果需要继续搜索，先调用工具再输出 JSON。
"""

        try:
            _emit_progress(emit_progress, f"Iteration {iteration}: asking LLM to synthesize the current SearchPlan.")
            raw_output = _invoke_llm(
                settings,
                SEARCHPLAN_SYSTEM_PROMPT,
                FEW_SHOT_EXAMPLES,
                user_prompt,
            )
        except Exception as exc:
            logger.warning("迭代 %d LLM 调用失败: %s", iteration, exc)
            warnings.append(f"迭代 {iteration} LLM 调用失败：{exc}")
            memory.last_action = f"llm_failed: {exc}"
            _emit_progress(emit_progress, f"Iteration {iteration}: LLM call failed with {exc}.")
            # 降级到 policy fallback plan
            if plan is None:
                plan = to_fallback_plan(brief)
                warnings.append("LLM 失败，降级到 policy fallback plan")
                _emit_progress(emit_progress, "Using fallback plan after repeated LLM failure.")
            continue

        data = _parse_json(raw_output)
        if data:
            new_plan = _validate_plan(data)
            if new_plan is not None:
                plan = new_plan
                _emit_progress(
                    emit_progress,
                    f"Iteration {iteration}: generated a valid SearchPlan with {len(plan.query_groups)} query groups.",
                )

        # ── Stop check（本次迭代结束后）────────────────────────────────────
        if plan is not None:
            stop, stop_reason = should_stop(memory, plan)
            if stop:
                memory.last_action = f"stop: {stop_reason}"
                _emit_progress(emit_progress, f"Stopping planner: {stop_reason}.")
                break

    # ── 最终兜底 ────────────────────────────────────────────────────────────
    if plan is None:
        warnings.append("Agent loop 未生成有效 plan，使用 fallback")
        plan = to_fallback_plan(brief)
        memory.last_action = "fallback"
        memory.planner_reflections.append("Fallback plan used")
        _emit_progress(emit_progress, "Planner produced no valid output; falling back to policy-generated plan.")

    _emit_progress(
        emit_progress,
        f"Search planning finished after {memory.iteration_count} iterations; remaining budget={memory.remaining_budget}.",
    )

    return SearchPlanResult(
        plan=plan,
        memory=memory,
        warnings=warnings,
        raw_model_output=raw_output,
    )


# ─── 查询提议策略 ───────────────────────────────────────────────────────────────


def _propose_queries(
    iteration: int,
    topic: str,
    expanded_kw: list[str],
    memory: SearchPlannerMemory,
) -> list[str]:
    """根据迭代次数和当前状态提议候选查询列表。"""
    queries: list[str] = []

    if iteration == 1:
        # 第一轮：直接搜索主题 + 最核心的关键词
        queries.append(topic)
        if expanded_kw:
            queries.append(expanded_kw[0])

    elif iteration == 2:
        # 第二轮：扩展方向（如果有关键词）
        if len(expanded_kw) > 1:
            queries.append(expanded_kw[1])
        queries.append(f"{topic} survey review")
        queries.append(f"{topic} benchmark dataset")

    elif iteration == 3:
        # 第三轮：方法细化和应用方向
        if len(expanded_kw) > 2:
            queries.append(expanded_kw[2])
        queries.append(f"{topic} application")
        queries.append(f"{topic} limitation")

    else:
        # 后续迭代：针对 empty queries 和 coverage gap
        for eq in memory.empty_queries[-3:]:
            if eq not in memory.attempted_queries:
                queries.append(f"{eq} tutorial")
        # 针对 subquestion gaps（如果有）
        for kw in expanded_kw[3:6]:
            if kw not in memory.attempted_queries:
                queries.append(kw)

    # 兜底：确保至少有一个查询
    if not queries:
        queries = [topic]

    # 去重（已尝试过的跳过）
    return [q for q in queries if q not in memory.attempted_queries]

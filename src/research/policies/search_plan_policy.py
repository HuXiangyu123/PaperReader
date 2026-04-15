"""SearchPlanAgent 策略：校验、停止条件、fallback。"""

from __future__ import annotations

import re

from src.models.research import SearchPlan, SearchPlannerMemory

MAX_ITERATIONS = 10
MIN_COVERAGE_SCORE = 0.6  # 覆盖率低于此值时应继续搜索

_TOPIC_CLAUSE_SPLIT_RE = re.compile(
    r"[，,。；;]\s*(输出|希望输出|产出|形式|重点关注|关注|聚焦|重点看|并关注)\b.*$",
    re.IGNORECASE,
)
_LEADING_RESEARCH_PREFIX_RE = re.compile(
    r"^(请|帮我|麻烦|想|需要)?\s*(调研|研究|分析|梳理|看看|了解)\s*",
)
_LEADING_TIME_RANGE_RE = re.compile(
    r"^(近[一二两三四五六七八九十\d]+年|最近|近几年|20\d{2}\s*[-~—–至到]\s*20\d{2}\s*年?)\s*",
)


def is_plan_valid(plan: SearchPlan) -> bool:
    """校验 SearchPlan 是否满足最低质量要求。"""
    if not plan.plan_goal:
        return False
    if not plan.query_groups:
        return False
    total_queries = sum(len(g.queries) for g in plan.query_groups)
    if total_queries == 0:
        return False
    return True


def should_stop(memory: SearchPlannerMemory, plan: SearchPlan) -> tuple[bool, str]:
    """判断是否应停止 agent 循环。返回 (should_stop, reason)。"""
    if memory.remaining_budget <= 0:
        return True, "预算耗尽"

    if memory.iteration_count >= MAX_ITERATIONS:
        return True, f"已达最大迭代次数 {MAX_ITERATIONS}"

    # 连续两次 iteration 没有新增覆盖
    if memory.iteration_count >= 2:
        recent_reflections = memory.planner_reflections[-2:]
        if all("no_improvement" in r or "degraded" in r for r in recent_reflections):
            return True, "连续两次迭代无改善"

    # 已有有效 plan 且覆盖充分
    if is_plan_valid(plan):
        # 检查是否所有 query groups 都有预期数量的 hits
        all_have_hits = all(
            memory.query_to_hits.get(q, 0) > 0
            for g in plan.query_groups
            for q in g.queries
        )
        if all_have_hits:
            return True, "所有查询均已有命中"

    return False, ""


def _clean_topic(raw_topic: str | None) -> str:
    topic = (raw_topic or "").strip().strip("。！？；;,.， ")
    if not topic:
        return "unknown"

    topic = _TOPIC_CLAUSE_SPLIT_RE.sub("", topic).strip("。！？；;,.， ")
    topic = _LEADING_RESEARCH_PREFIX_RE.sub("", topic).strip()
    topic = _LEADING_TIME_RANGE_RE.sub("", topic).strip()
    topic = re.sub(r"\s+", " ", topic).strip("。！？；;,.， ")
    return topic or "unknown"


def _compose_query(text: str, extras: list[str]) -> str:
    parts = [text.strip(), *[extra.strip() for extra in extras if extra and extra.strip()]]
    return " ".join(dict.fromkeys(parts)).strip()


def to_fallback_plan(brief: dict) -> SearchPlan:
    """从原始 brief 生成最保守的 fallback plan。"""
    raw_topic = brief.get("research_topic", brief.get("topic", "unknown"))
    topic = _clean_topic(raw_topic)
    time_range = (brief.get("time_range") or "").strip()
    domain_scope = (brief.get("domain_scope") or "").strip()
    focus_dimensions = [str(item).strip() for item in brief.get("focus_dimensions", []) if str(item).strip()]
    keywords = brief.get("keywords", brief.get("key_terms", []))
    kw_list = [str(item).strip() for item in (keywords if isinstance(keywords, list) else [keywords]) if str(item).strip()]

    primary_query = _compose_query(topic, [time_range])
    focus_queries = [_compose_query(topic, [time_range, focus]) for focus in focus_dimensions[:2]]
    scope_query = _compose_query(topic, [time_range, domain_scope])

    queries: list[str] = []
    for candidate in [primary_query, scope_query, *focus_queries, *kw_list[:3]]:
        if candidate and candidate not in queries:
            queries.append(candidate)

    if not queries:
        queries = [topic]

    goal_prefix = f"{time_range} " if time_range else ""
    plan_goal = f"围绕 {goal_prefix}{topic} 制定相关研究检索计划".strip()
    followup_needed = bool(brief.get("needs_followup")) or topic == "unknown"

    return SearchPlan(
        schema_version="v1",
        plan_goal=plan_goal,
        query_groups=[
            {
                "group_id": "fallback_g1",
                "queries": queries,
                "intent": "broad",
                "priority": 1,
                "expected_hits": 10,
                "notes": "Heuristic fallback synthesized from available brief fields",
            }
        ],
        source_preferences=["arxiv", "semantic_scholar"],
        dedup_strategy="semantic",
        rerank_required=True,
        max_candidates_per_query=20,
        requires_local_corpus=False,
        coverage_notes="Heuristic fallback plan synthesized from available brief fields",
        planner_warnings=["SearchPlanAgent 生成失败，使用 fallback"],
        followup_needed=followup_needed,
    )

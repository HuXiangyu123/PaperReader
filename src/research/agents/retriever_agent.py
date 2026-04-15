"""RetrieverAgent — Tool-Augmented Generation (TAG) 模式。

设计模式说明：
- TAG = Tool-Augmented Generation：在 LLM 推理时实时调用工具增强生成质量。
- 核心思想：LLM 生成每一步时，按需调用外部工具（检索、查表），
  将工具结果无缝注入推理链，而不是事后 post-hoc 拼接检索结果。
- 适用场景：需要实时、精确外部知识的检索任务。

与 ReAct 的区别：
- ReAct：显式循环（Observe → Think → Act → ...），工具调用是独立步骤
- TAG：工具是推理链中的内联增强（LLM 自驱动按需调用），无需显式循环
- TAG 更适合："我需要查一下 X" 这类即时知识需求

阶段划分：
  Phase 1 (Augmented Query Generation):
      LLM 生成查询，同时内联调用 expand_keywords / rewrite_query 增强查询质量
  Phase 2 (Parallel Retrieval):
      批量并行检索，工具结果作为 LLM 推理的 context
  Phase 3 (Context Assembly):
      LLM 基于检索结果内联生成（直接输出最终 candidate list）
"""

from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Any
from typing import TypedDict

from langgraph.graph import START, StateGraph
from src.memory.manager import get_memory_manager
from src.models.paper import RagResult

logger = logging.getLogger(__name__)


# ─── TAG Prompt Templates ────────────────────────────────────────────────────


AUGMENTED_QUERY_PROMPT = """你是一个查询生成专家。给定研究主题和子问题，按需调用工具增强查询质量。

工作方式：
- 直接生成增强后的查询列表
- 如需关键词扩展或查询重写，请在 <tools> 标签内说明工具调用
- 最终只输出 JSON 格式的查询列表

<tools>
可选工具：expand_keywords(topic, dimension), rewrite_query(query, mode)
</tools>

输出（严格 JSON）：
```json
{{
  "queries": [
    {{
      "query": "增强后的查询文本",
      "sources": ["arxiv", "semantic_scholar"],
      "tools_used": ["expand_keywords"],
      "expected_hits": 20
    }}
  ]
}}
```
"""


CONTEXT_ASSEMBLY_PROMPT = """你是一个检索上下文组装专家。

给定以下检索结果（来自多个来源），请直接生成最终的高质量论文候选列表。

规则：
1. 去重（相同 arXiv ID 或 URL 只保留一个）
2. 按相关性排序（标题相关度 > 摘要相关度）
3. 每条记录必须包含：title, url, abstract(前200字), source
4. 最终输出直接是 JSON array，不要额外解释

输出（严格 JSON array）：
```json
[
  {{"rank": 1, "title": "...", "url": "...", "abstract": "...", "source": "arxiv"}},
  ...
]
```
数量限制：最多 {max_candidates} 条
"""


# ─── RetrieverAgent ──────────────────────────────────────────────────────────


class RetrieverAgent:
    """
    Tool-Augmented Generation 模式的 Retriever Agent。

    工作流程：
      ┌────────────────────────┐
      │ AUGMENTED QUERY GEN    │  LLM 生成 + 内联工具增强（expand/rewrite）
      └──────────┬─────────────┘
                 │ augmented queries
                 ▼
      ┌────────────────────────┐
      │ PARALLEL RETRIEVAL     │  并行执行多源检索（SearXNG + local corpus）
      └──────────┬─────────────┘
                 │ raw results
                 ▼
      ┌────────────────────────┐
      │ CONTEXT ASSEMBLY       │  LLM 内联推理：直接基于检索结果生成最终 candidate list
      │ (TAG 核心)             │  不再经过中间状态，工具结果 → LLM 直接输出
      └──────────┬─────────────┘
                 │ final candidates
    """

    def __init__(self, workspace_id: str | None = None, task_id: str | None = None):
        self.workspace_id = workspace_id
        self.task_id = task_id
        self.mm = get_memory_manager(workspace_id) if workspace_id else None

    # ── Phase 1: Augmented Query Generation ─────────────────────────────────

    def _augmented_query_gen(self, brief: dict) -> dict[str, Any]:
        """
        Phase 1: 增强查询生成。

        TAG 的关键：LLM 推理时自驱动调用工具，不是预先定义好的调用。
        这里模拟 LLM 自驱动：先问 LLM "需要哪些工具"，然后执行，再继续。
        """
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage
        from src.tools.search_tools import _searxng_search

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=4096)

        topic = brief.get("research_topic") or brief.get("topic", "")
        sub_questions = brief.get("sub_questions", [])
        if isinstance(sub_questions, str):
            sub_questions = [sub_questions]
        sq_text = "\n".join(f"- {sq}" for sq in sub_questions) if sub_questions else "无"

        brief_text = f"Topic: {topic}\nSub-questions:\n{sq_text}"

        # LLM 生成初始查询 + 判断是否需要工具增强
        try:
            resp = llm.invoke([
                SystemMessage(content=AUGMENTED_QUERY_PROMPT),
                HumanMessage(content=brief_text),
            ])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            query_data = self._parse_json(raw)
        except Exception as exc:
            logger.warning("[RetrieverAgent] augmented query gen failed: %s", exc)
            query_data = None

        if not query_data or "queries" not in query_data:
            # Fallback：直接生成基础查询
            queries = [{"query": topic, "sources": ["arxiv"], "expected_hits": 20}]
            query_data = {"queries": queries}

        # TAG 内联增强：按需调用工具
        augmented_queries = []
        for item in query_data.get("queries", []):
            q = item.get("query", "")
            if not q:
                continue

            # 检查是否需要 expand_keywords（模拟 LLM 自驱动判断）
            if len(q) > 5 and len(sub_questions) > 1:
                try:
                    from src.tools.search_tools import expand_keywords as _expand_fn

                    kw_result = _expand_fn.invoke({"topic": q, "focus_dimension": "methods"})
                    expanded = [l.strip("- ").strip() for l in kw_result.split("\n") if l.strip()]
                    if expanded:
                        q = expanded[0]
                        if self.mm:
                            self.mm.add_tool_output("expand_keywords", {"original": item["query"], "expanded": expanded})
                except Exception:
                    pass

            # 检查是否需要 rewrite_query
            if len(q) > 30:
                try:
                    from src.tools.search_tools import rewrite_query as _rewrite_fn

                    rewritten = _rewrite_fn.invoke({"query": q, "mode": "precise"})
                    if rewritten and len(rewritten) < len(q):
                        q = rewritten
                        if self.mm:
                            self.mm.add_tool_output("rewrite_query", {"original": item["query"], "rewritten": q})
                except Exception:
                    pass

            item["query"] = q
            augmented_queries.append(item)

        if self.mm:
            self.mm.add_sensory("augmented_queries", {"queries": augmented_queries})

        return {"queries": augmented_queries, "phase": "augmented_query_gen"}

    # ── Phase 2: Parallel Retrieval ─────────────────────────────────────────

    def _parallel_retrieval(self, queries: list[dict]) -> dict[str, Any]:
        """
        Phase 2: 并行多源检索。

        TAG 的特点：工具结果是推理链的 context，而不是最终输出。
        这里将所有工具调用结果打包，供 Phase 3 内联使用。
        """
        import concurrent.futures

        from src.tools.search_tools import _searxng_search

        all_results: list[dict] = []

        def _retrieve_one(item: dict) -> dict:
            q = item.get("query", "")
            sources = item.get("sources", ["arxiv"])
            expected_hits = item.get("expected_hits", 20)
            engines = ",".join(sources)

            result = _searxng_search(q, engines=engines, max_results=expected_hits)
            result["query"] = q
            result["query_meta"] = item
            return result

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(queries))) as pool:
                futures = {pool.submit(_retrieve_one, q): q for q in queries}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                        all_results.append(result)
                        if self.mm:
                            self.mm.add_tool_output(
                                "searxng",
                                {"query": result.get("query"), "hit_count": len(result.get("hits", []))},
                            )
                    except Exception as exc:
                        logger.warning("[RetrieverAgent] retrieval failed for query: %s", exc)
        except Exception as exc:
            logger.warning("[RetrieverAgent] parallel retrieval failed: %s", exc)

        return {"raw_results": all_results, "phase": "parallel_retrieval"}

    # ── Phase 3: Context Assembly (TAG 核心) ─────────────────────────────────

    def _context_assembly(self, brief: dict, raw_results: list[dict]) -> list[dict]:
        """
        Phase 3: 上下文组装（TAG 核心）。

        TAG 与 ReAct 的本质区别：
        - ReAct: 工具调用 → 观察结果 → LLM 推理 → 再调用 → ...
        - TAG:   工具调用 → 直接作为 LLM context → LLM 内联输出最终结果

        这里 LLM 直接基于原始检索结果推理，输出去重排序后的 candidate list，
        不经过中间状态转换。
        """
        from src.agent.llm import build_reason_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage

        settings = get_settings()
        llm = build_reason_llm(settings, max_tokens=8192)

        # 将检索结果整理为 LLM 可读的上下文
        context_lines = []
        for res in raw_results:
            q = res.get("query", "?")
            hits = res.get("hits", [])
            sources = res.get("query_meta", {}).get("sources", [])
            context_lines.append(f"## 查询: {q} (来源: {sources})")
            for i, hit in enumerate(hits[:10], 1):
                context_lines.append(
                    f"  [{i}] {hit.get('title', 'Unknown')}\n"
                    f"      URL: {hit.get('url', '')}\n"
                    f"      摘要: {hit.get('content', '')[:300]}"
                )
            context_lines.append("")

        context_text = "\n".join(context_lines)
        max_candidates = 30

        topic = brief.get("research_topic") or brief.get("topic", "")

        user_prompt = f"""## 研究主题

{topic}

## 检索结果上下文

{context_text}

{CONTEXT_ASSEMBLY_PROMPT.replace("{max_candidates}", str(max_candidates))}
"""

        try:
            resp = llm.invoke([
                SystemMessage(content="你是一个检索结果组装专家。直接输出 JSON，不要解释。"),
                HumanMessage(content=user_prompt),
            ])
            raw = resp.content if hasattr(resp, "content") else str(resp)
            candidates = self._parse_json_array(raw)
        except Exception as exc:
            logger.warning("[RetrieverAgent] context assembly failed: %s", exc)
            candidates = []

        if not candidates:
            # Fallback：直接从 raw results 提取
            candidates = self._fallback_candidates(raw_results)

        return candidates

    # ── 完整 Pipeline ─────────────────────────────────────────────────────

    def run(self, brief: dict, search_plan: dict | None = None) -> dict[str, Any]:
        """
        完整 TAG Pipeline。

        流程：augmented_query_gen → parallel_retrieval → context_assembly
        """
        logger.info("[RetrieverAgent] Starting TAG pipeline via LangGraph")
        result = self.build_graph().invoke(
            {
                "brief": brief,
                "search_plan": search_plan or {},
                "warnings": [],
            }
        )
        rag_result = result.get("rag_result")
        candidates = []
        if isinstance(rag_result, dict):
            candidates = list(rag_result.get("paper_candidates", []))

        logger.info("[RetrieverAgent] TAG pipeline done: %d candidates", len(candidates))
        return {
            "rag_result": rag_result,
            "raw_results_count": int(result.get("raw_results_count", 0)),
            "queries_generated": int(result.get("queries_generated", 0)),
            "paradigm": "tag",
            "summary": (
                f"TAG pipeline 完成：{int(result.get('queries_generated', 0))} 个增强查询 → "
                f"{len(candidates)} 篇候选论文"
            ),
            "retriever_warnings": list(result.get("warnings", [])),
        }

    # ── Fallback ─────────────────────────────────────────────────────────

    def _fallback_candidates(self, raw_results: list[dict]) -> list[dict]:
        """从 raw results 直接提取 candidate（当 context_assembly 失败时）。"""
        seen_urls: set[str] = set()
        candidates: list[dict] = []
        rank = 1

        for res in raw_results:
            for hit in res.get("hits", []):
                url = hit.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                candidates.append({
                    "rank": rank,
                    "title": hit.get("title", ""),
                    "url": url,
                    "abstract": hit.get("content", "")[:500],
                    "source": hit.get("engine", "arxiv"),
                })
                rank += 1
                if rank > 30:
                    break
            if rank > 30:
                break

        return candidates

    # ── Helpers ─────────────────────────────────────────────────────────

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

    def _parse_json_array(self, text: str) -> list:
        import json

        text = text.strip()
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return []

    def build_graph(self):
        workflow = StateGraph(RetrieverGraphState)
        workflow.add_node("augmented_query_gen", self._query_node)
        workflow.add_node("parallel_retrieval", self._retrieval_node)
        workflow.add_node("context_assembly", self._assembly_node)
        workflow.add_node("finalize_rag_result", self._finalize_node)
        workflow.add_edge(START, "augmented_query_gen")
        workflow.add_edge("augmented_query_gen", "parallel_retrieval")
        workflow.add_edge("parallel_retrieval", "context_assembly")
        workflow.add_edge("context_assembly", "finalize_rag_result")
        return workflow.compile()

    def _query_node(self, state: "RetrieverGraphState") -> dict[str, Any]:
        result = self._augmented_query_gen(state.get("brief") or {})
        queries = list(result.get("queries", []))
        if self.mm:
            self.mm.add_sensory(
                "phase_completed",
                {"phase": "augmented_query_gen", "query_count": len(queries)},
            )
        return {"queries": queries, "queries_generated": len(queries)}

    def _retrieval_node(self, state: "RetrieverGraphState") -> dict[str, Any]:
        result = self._parallel_retrieval(list(state.get("queries", [])))
        raw_results = list(result.get("raw_results", []))
        return {
            "raw_results": raw_results,
            "raw_results_count": len(raw_results),
        }

    def _assembly_node(self, state: "RetrieverGraphState") -> dict[str, Any]:
        candidates = self._context_assembly(
            state.get("brief") or {},
            list(state.get("raw_results", [])),
        )
        if self.mm and candidates:
            try:
                for cand in candidates[:5]:
                    self.mm.add_semantic(
                        f"检索到论文: {cand.get('title', '')[:100]}",
                        memory_type="research_fact",
                        metadata={"source": "retriever_agent", "workspace_id": self.workspace_id},
                    )
            except Exception as exc:
                logger.warning("[RetrieverAgent] Failed to store semantic memory: %s", exc)
        return {"candidates": candidates}

    def _finalize_node(self, state: "RetrieverGraphState") -> dict[str, Any]:
        candidates = list(state.get("candidates", []))
        rag_result = self._build_rag_result(
            brief=state.get("brief") or {},
            search_plan=state.get("search_plan") or {},
            raw_results=list(state.get("raw_results", [])),
            candidates=candidates,
        )
        return {"rag_result": rag_result}

    def _build_rag_result(
        self,
        *,
        brief: dict[str, Any],
        search_plan: dict[str, Any],
        raw_results: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from src.research.graph.nodes.search import _ingest_paper_candidates

        query = search_plan.get("plan_goal") or brief.get("research_topic") or brief.get("topic", "")
        query_traces = []
        for result in raw_results:
            query_traces.append(
                {
                    "query": result.get("query", ""),
                    "status": "success" if result.get("ok", True) else "error",
                    "hits_count": len(result.get("hits", [])),
                }
            )

        rag_result = RagResult(
            query=query,
            sub_questions=list(brief.get("sub_questions", [])) if isinstance(brief.get("sub_questions"), list) else [],
            rag_strategy="tag_augmented_query + parallel_retrieval + context_assembly",
            paper_candidates=candidates,
            evidence_chunks=[],
            retrieval_trace=query_traces,
            dedup_log=[{"strategy": "url/title", "total": len(candidates), "unique": len(candidates)}],
            rerank_log=[],
            coverage_notes=[
                f"TAG agent 执行 {len(raw_results)} 组检索，组装出 {len(candidates)} 篇候选论文",
            ],
            total_papers=len(candidates),
            total_chunks=0,
            retrieved_at="",
        )
        try:
            _ingest_paper_candidates(candidates, workspace_id=self.workspace_id)
        except Exception as exc:
            logger.warning("[RetrieverAgent] Failed to ingest candidates: %s", exc)
        return asdict(rag_result)


class RetrieverGraphState(TypedDict, total=False):
    brief: dict[str, Any]
    search_plan: dict[str, Any]
    warnings: list[str]
    queries: list[dict[str, Any]]
    queries_generated: int
    raw_results: list[dict[str, Any]]
    raw_results_count: int
    candidates: list[dict[str, Any]]
    rag_result: dict[str, Any]


# ─── 入口函数 ────────────────────────────────────────────────────────────────


def run_retriever_agent(state: dict, inputs: dict) -> dict:
    """RetrieverAgent 入口（兼容 supervisor 格式）。"""
    workspace_id = inputs.get("workspace_id") or state.get("workspace_id")
    task_id = inputs.get("task_id") or state.get("task_id")
    brief = state.get("brief") or inputs.get("brief", {})
    search_plan = state.get("search_plan")

    agent = RetrieverAgent(workspace_id=workspace_id, task_id=task_id)
    try:
        return agent.run(brief=brief, search_plan=search_plan)
    except Exception as exc:
        logger.exception("[RetrieverAgent] run failed: %s", exc)
        return {
            "candidates": [],
            "paradigm": "tag",
            "retriever_warnings": [f"RetrieverAgent failed: {exc}"],
        }

"""Skill Orchestrator — Agent-driven skill selection and chaining.

Design:
- Skills are wrapped as LangChain tools
- A lightweight LLM agent decides which skills to invoke based on user intent
- Supports both explicit invocation (/skill_id) and implicit (agent decides)
- Skill results feed back into the agent for further reasoning

Workflow:
  User message
    ↓
  SkillOrchestrator.analyze(user_msg)
    ├── Explicit /skill_id → route directly
    └── Implicit → LLM decides skill(s) to call
         ↓
    Skills execute in sequence (if chained)
         ↓
    Results aggregated → final response
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.skills.registry import get_skills_registry

logger = logging.getLogger(__name__)


# ─── Skill tool wrapper ───────────────────────────────────────────────────────


class SkillTool:
    """
    Wraps a skill as a callable tool for LLM agent use.

    Exposes: name, description, args_schema → can be used as a LangChain tool
    """

    def __init__(self, skill_id: str, name: str, description: str, input_schema: dict):
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.input_schema = input_schema

    def __repr__(self) -> str:
        return f"<SkillTool {self.skill_id}>"

    @property
    def args_schema(self) -> dict:
        return self.input_schema


# ─── Orchestrator ─────────────────────────────────────────────────────────────


class SkillOrchestrator:
    """
    Agent-driven skill orchestrator.

    Given a user message (optionally with /skill_id prefix), decides which skills
    to invoke and chains them together. Results are aggregated and returned.

    Two modes:
    1. Explicit: message starts with /skill_id → invoke that skill directly
    2. Implicit: agent decides which skills to use based on message intent
    """

    def __init__(
        self,
        workspace_id: str | None = None,
        task_id: str | None = None,
    ):
        self.workspace_id = workspace_id
        self.task_id = task_id
        self._registry = get_skills_registry()

    def list_tools(self) -> list[SkillTool]:
        """List all available skill tools."""
        tools = []
        for manifest in self._registry.list_all():
            tools.append(SkillTool(
                skill_id=manifest.skill_id,
                name=manifest.name,
                description=manifest.description,
                input_schema=manifest.input_schema,
            ))
        return tools

    async def analyze(
        self,
        user_message: str,
        context: dict | None = None,
    ) -> dict[str, Any]:
        """
        Main entry point: decide what to do with user_message.

        Returns:
            {
                "mode": "skill" | "chat" | "chain",
                "skill_id": "...",          # for mode=skill
                "chain": [...],               # for mode=chain
                "response": "...",           # final aggregated response
                "skill_results": [...],       # individual skill results
                "tool_calls": [...],          # trace of tool invocations
            }
        """
        ctx = context or {}
        msg = user_message.strip()

        # ── Mode 1: Explicit /skill_id ──────────────────────────────────────
        if msg.startswith("/"):
            parts = msg[1:].split(None, 1)
            skill_id = parts[0]
            skill_args_raw = parts[1] if len(parts) > 1 else ""

            # Parse args as JSON or as key=value pairs
            skill_args = self._parse_skill_args(skill_args_raw)

            result = await self._invoke_skill(skill_id, skill_args, ctx)
            return {
                "mode": "skill",
                "skill_id": skill_id,
                "response": result.get("summary", str(result)),
                "skill_results": [result],
                "tool_calls": [self._tool_call_record(skill_id, skill_args, result)],
            }

        # ── Mode 2: Implicit — let LLM decide ───────────────────────────────
        # Use a lightweight LLM to decide if any skills should be invoked
        tool_summaries = self._build_tool_summaries()
        decision = await self._llm_decide_tools(msg, tool_summaries, ctx)

        if not decision.get("should_use_skills"):
            return {
                "mode": "chat",
                "skill_id": None,
                "response": None,  # Hand off to normal chat
                "skill_results": [],
                "tool_calls": [],
                "llm_reasoning": decision.get("reasoning"),
            }

        # ── Mode 3: Chain of skills ─────────────────────────────────────────
        skill_chain = decision.get("skill_chain", [])
        skill_results = []
        tool_calls = []
        aggregated_context = dict(ctx)

        for skill_entry in skill_chain:
            skill_id = skill_entry.get("skill_id") or skill_entry.get("name")
            args = skill_entry.get("args", {})
            # Merge previous results into context for next skill
            if skill_results:
                aggregated_context["_previous_results"] = [
                    {"skill": r.get("skill_id"), "summary": r.get("summary", "")}
                    for r in skill_results
                ]

            result = await self._invoke_skill(skill_id, args, aggregated_context)
            skill_results.append(result)
            tool_calls.append(self._tool_call_record(skill_id, args, result))

        # Build final response
        response = self._build_chain_response(skill_chain, skill_results)

        return {
            "mode": "chain",
            "skill_id": None,
            "response": response,
            "skill_results": skill_results,
            "tool_calls": tool_calls,
            "llm_reasoning": decision.get("reasoning"),
        }

    async def _llm_decide_tools(
        self,
        user_message: str,
        tool_summaries: str,
        context: dict,
    ) -> dict:
        """
        Use a lightweight LLM to decide which skills (if any) to invoke.

        Returns:
            {
                "should_use_skills": bool,
                "skill_chain": [{"skill_id": "...", "args": {...}}],
                "reasoning": "...",
            }
        """
        from src.agent.llm import build_quick_llm
        from src.agent.settings import get_settings
        from langchain_core.messages import HumanMessage, SystemMessage

        brief = context.get("brief", {})
        topic = brief.get("topic", "") if isinstance(brief, dict) else ""

        system_prompt = f"""You are a skill orchestrator. Given a user message and available skills, decide which skills to invoke.

Available skills:
{tool_summaries}

Respond with ONLY valid JSON (no markdown):
{{
  "should_use_skills": true/false,
  "skill_chain": [
    {{"skill_id": "skill_id_here", "args": {{"key": "value"}}}}
  ],
  "reasoning": "brief explanation"
}}

Rules:
- If the message is a simple question that doesn't need a skill, set should_use_skills=false
- If multiple skills are relevant, chain them in logical order
- Only use skill_ids from the available skills list
- args should contain the inputs needed by the skill
- Keep reasoning to 1-2 sentences
"""

        user_prompt = f"User message: {user_message}\nResearch topic: {topic}"

        try:
            settings = get_settings()
            llm = build_quick_llm(settings, max_tokens=1024)
            resp = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            raw = resp.content if hasattr(resp, "content") else ""
            # Extract JSON
            raw = raw.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                return {
                    "should_use_skills": bool(data.get("should_use_skills", False)),
                    "skill_chain": data.get("skill_chain", []),
                    "reasoning": data.get("reasoning", ""),
                }
        except Exception as exc:
            logger.warning("[SkillOrchestrator] LLM decision failed: %s", exc)

        return {"should_use_skills": False, "skill_chain": [], "reasoning": "LLM unavailable"}

    async def _invoke_skill(
        self,
        skill_id: str,
        args: dict,
        context: dict,
    ) -> dict:
        """Invoke a single skill via the registry."""
        from src.models.skills import SkillRunRequest

        req = SkillRunRequest(
            skill_id=skill_id,
            workspace_id=self.workspace_id or context.get("workspace_id", ""),
            task_id=self.task_id or context.get("task_id"),
            inputs=args,
        )
        ctx = {
            "workspace_id": req.workspace_id,
            "task_id": req.task_id,
            **context,
        }

        try:
            resp = await self._registry.run(req, ctx)
            return {
                "skill_id": resp.skill_id,
                "summary": resp.summary,
                "output_artifact_ids": resp.output_artifact_ids,
                "backend": resp.backend.value,
            }
        except Exception as exc:
            logger.error("[SkillOrchestrator] skill %s failed: %s", skill_id, exc)
            return {
                "skill_id": skill_id,
                "error": str(exc),
                "summary": f"Skill {skill_id} failed: {exc}",
            }

    def _build_tool_summaries(self) -> str:
        """Build a readable list of available tools for LLM consumption."""
        lines = []
        for tool in self.list_tools():
            schema_desc = json.dumps(tool.input_schema, ensure_ascii=False, indent=2)
            lines.append(f"- skill_id: {tool.skill_id}")
            lines.append(f"  name: {tool.name}")
            lines.append(f"  description: {tool.description}")
            if tool.input_schema:
                lines.append(f"  args: {schema_desc}")
        return "\n".join(lines) if lines else "(no skills available)"

    def _parse_skill_args(self, raw: str) -> dict:
        """Parse skill arguments from raw string (JSON or key=value pairs)."""
        raw = raw.strip()
        if not raw:
            return {}

        # Try JSON first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Parse key=value pairs
        args = {}
        for part in raw.split():
            if "=" in part:
                key, val = part.split("=", 1)
                args[key.strip()] = val.strip()
        return args

    def _build_chain_response(self, chain: list, results: list) -> str:
        """Build a human-readable response from a skill chain."""
        if not results:
            return "No results."

        parts = []
        for entry, result in zip(chain, results):
            skill_id = entry.get("skill_id", "unknown")
            summary = result.get("summary", result.get("error", "No result"))
            parts.append(f"**{skill_id}**: {summary}")

        return "Skill chain results:\n\n" + "\n\n".join(parts)

    def _tool_call_record(
        self,
        skill_id: str,
        args: dict,
        result: dict,
    ) -> dict:
        """Build a tool call trace record."""
        return {
            "tool": skill_id,
            "args": args,
            "success": "error" not in result,
            "summary": result.get("summary", result.get("error", "")),
        }


# ─── Convenience API ─────────────────────────────────────────────────────────


async def orchestrate(
    user_message: str,
    workspace_id: str | None = None,
    task_id: str | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """
    Convenience function: orchestrate skill execution from user message.

    Usage:
        result = await orchestrate("/citation_verifier query=attention mechanism")
        result = await orchestrate("帮我分析这些论文的方法对比")
    """
    orchestrator = SkillOrchestrator(
        workspace_id=workspace_id,
        task_id=task_id,
    )
    ctx = context or {}
    ctx.setdefault("workspace_id", workspace_id or "")
    ctx.setdefault("task_id", task_id or "")
    return await orchestrator.analyze(user_message, ctx)

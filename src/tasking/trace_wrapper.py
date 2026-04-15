"""Trace wrapper — @trace_node / @trace_tool decorators + context managers.

Wraps graph nodes and tool calls with structured NodeRun / ToolRun tracking.
Does NOT change the wrapped function's internal logic.
"""

from __future__ import annotations

import time
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from src.models.trace import NodeRun, RunStatus, ToolRun, TraceEvent, TraceEventType

logger = logging.getLogger(__name__)


# ─── Shared context ─────────────────────────────────────────────────────────────


class TraceContext:
    """
    在 node 执行过程中共享的 trace 上下文。

    通过 contextvars 或直接传递注入到 wrapper 中。
    """

    def __init__(
        self,
        task_id: str = "",
        workspace_id: str = "",
        event_handler: Callable[[TraceEvent], None] | None = None,
    ):
        self.task_id = task_id
        self.workspace_id = workspace_id
        self.event_handler = event_handler
        self._active_runs: dict[str, NodeRun] = {}

    def emit(self, event: TraceEvent) -> None:
        if self.event_handler:
            self.event_handler(event)
        logger.debug(
            f"[Trace] {event.event_type.value} task={self.task_id} "
            f"run={event.run_id} tool={getattr(event, 'tool_run_id', 'n/a')}"
        )

    def active_run(self, node_name: str) -> NodeRun | None:
        return self._active_runs.get(node_name)

    def set_active_run(self, node_name: str, run: NodeRun) -> None:
        self._active_runs[node_name] = run

    def clear_active_run(self, node_name: str) -> None:
        self._active_runs.pop(node_name, None)


# ─── Default in-memory store ────────────────────────────────────────────────────


class InMemoryTraceStore:
    """
    进程内内存存储，用于开发和测试。

    生产环境应替换为 PostgreSQL / Redis / S3 持久化。
    """

    def __init__(self):
        self.node_runs: list[NodeRun] = []
        self.tool_runs: list[ToolRun] = []
        self.events: list[TraceEvent] = []

    def save_node_run(self, run: NodeRun) -> None:
        self.node_runs.append(run)

    def save_tool_run(self, run: ToolRun) -> None:
        self.tool_runs.append(run)

    def save_event(self, event: TraceEvent) -> None:
        self.events.append(event)

    def get_node_runs(self, task_id: str) -> list[NodeRun]:
        return [r for r in self.node_runs if r.task_id == task_id]

    def get_tool_runs(self, task_id: str) -> list[ToolRun]:
        return [r for r in self.tool_runs if r.task_id == task_id]

    def get_events(self, task_id: str) -> list[TraceEvent]:
        return [e for e in self.events if e.task_id == task_id]

    def get_latest_run(self, task_id: str, node_name: str) -> NodeRun | None:
        runs = [r for r in self.node_runs if r.task_id == task_id and r.node_name == node_name]
        return runs[-1] if runs else None

    def clear(self) -> None:
        self.node_runs.clear()
        self.tool_runs.clear()
        self.events.clear()


# Global singleton (replace with DI in production)
_trace_store: InMemoryTraceStore = InMemoryTraceStore()


def get_trace_store() -> InMemoryTraceStore:
    return _trace_store


# ─── @trace_node ────────────────────────────────────────────────────────────────


def trace_node(
    node_name: str,
    stage: str,
    store: InMemoryTraceStore | None = None,
    emit_sse: Callable[[TraceEvent], None] | None = None,
) -> Callable[[Callable], Callable]:
    """
    装饰 graph node 执行，自动记录 NodeRun + TraceEvent。

    用法：
        @trace_node(node_name="review", stage="review")
        async def review_node(state: dict) -> dict:
            ...

    Args:
        node_name: 节点名称（唯一标识）
        stage: 执行阶段（如 "review"、"revise"、"persist"）
        store: trace 持久化存储（默认使用进程内内存）
        emit_sse: 可选，实时 SSE 推送回调
    """

    def decorator(fn: Callable) -> Callable:
        _fn = fn  # avoid closure capture

        @wraps(fn)
        def wrapper(state: dict, *args, **kwargs) -> dict:
            _store = store or _trace_store
            task_id = str(state.get("task_id", ""))
            workspace_id = str(state.get("workspace_id", ""))

            # Build context
            ctx = TraceContext(
                task_id=task_id,
                workspace_id=workspace_id,
                event_handler=emit_sse,
            )

            run = NodeRun(
                task_id=task_id,
                workspace_id=workspace_id,
                node_name=node_name,
                stage=stage,
                status=RunStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            _store.save_node_run(run)
            ctx.set_active_run(node_name, run)

            # Emit node_started event
            started_evt = TraceEvent(
                task_id=task_id,
                workspace_id=workspace_id,
                run_id=run.run_id,
                event_type=TraceEventType.NODE_STARTED,
                payload={"node_name": node_name, "stage": stage},
            )
            _store.save_event(started_evt)
            ctx.emit(started_evt)

            try:
                # Inject trace context into state so child wrappers can find it
                local_state = dict(state)
                local_state["_trace_ctx"] = ctx

                result = _fn(local_state, *args, **kwargs)

                # Update run status
                run.status = RunStatus.SUCCEEDED
                run.ended_at = datetime.now(timezone.utc)
                if run.started_at:
                    run.duration_ms = int(
                        (run.ended_at - run.started_at).total_seconds() * 1000
                    )

                # Emit node_finished event
                finished_evt = TraceEvent(
                    task_id=task_id,
                    workspace_id=workspace_id,
                    run_id=run.run_id,
                    event_type=TraceEventType.NODE_FINISHED,
                    payload={
                        "node_name": node_name,
                        "duration_ms": run.duration_ms,
                    },
                )
                _store.save_event(finished_evt)
                ctx.emit(finished_evt)

                return result

            except Exception as exc:
                run.status = RunStatus.FAILED
                run.ended_at = datetime.now(timezone.utc)
                if run.started_at:
                    run.duration_ms = int(
                        (run.ended_at - run.started_at).total_seconds() * 1000
                    )
                run.error_message = str(exc)

                failed_evt = TraceEvent(
                    task_id=task_id,
                    workspace_id=workspace_id,
                    run_id=run.run_id,
                    event_type=TraceEventType.NODE_FAILED,
                    payload={
                        "node_name": node_name,
                        "error": str(exc),
                        "duration_ms": run.duration_ms,
                    },
                )
                _store.save_event(failed_evt)
                ctx.emit(failed_evt)

                raise

            finally:
                ctx.clear_active_run(node_name)

        return wrapper

    return decorator


# ─── @trace_tool ──────────────────────────────────────────────────────────────


def trace_tool(
    tool_name: str,
    store: InMemoryTraceStore | None = None,
    emit_sse: Callable[[TraceEvent], None] | None = None,
) -> Callable[[Callable], Callable]:
    """
    装饰 tool runtime 调用，自动记录 ToolRun + TraceEvent。

    用法：
        @trace_tool(tool_name="rag_search")
        async def run_rag_search(ctx, query: str):
            ...

    Note: 需要调用者传递 TraceContext（从 state["_trace_ctx"] 获取）。
    """

    def decorator(fn: Callable) -> Callable:
        _fn = fn

        @wraps(fn)
        def wrapper(ctx_or_state: dict | TraceContext, *args, **kwargs) -> Any:
            _store = store or _trace_store

            # Accept both TraceContext and dict-style state
            if isinstance(ctx_or_state, TraceContext):
                ctx = ctx_or_state
                task_id = ctx.task_id
                workspace_id = ctx.workspace_id
                node_name = ""
                parent_run: NodeRun | None = None
            else:
                ctx_or_state = dict(ctx_or_state)
                ctx = ctx_or_state.get("_trace_ctx")
                if ctx is None:
                    # No trace context — run without tracing
                    return _fn(ctx_or_state, *args, **kwargs)
                task_id = ctx.task_id or str(ctx_or_state.get("task_id", ""))
                workspace_id = ctx.workspace_id or str(ctx_or_state.get("workspace_id", ""))
                node_name = ctx.active_runs and next(
                    (n for n, r in ctx._active_runs.items() if r.status == RunStatus.RUNNING), ""
                ) or ""
                parent_run = ctx.active_run(node_name) if node_name else None

            parent_run_id = parent_run.run_id if parent_run else ""

            tool_run = ToolRun(
                task_id=task_id,
                workspace_id=workspace_id,
                node_name=node_name,
                tool_name=tool_name,
                parent_run_id=parent_run_id,
                status=RunStatus.RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            _store.save_tool_run(tool_run)

            started_evt = TraceEvent(
                task_id=task_id,
                workspace_id=workspace_id,
                run_id=parent_run_id,
                tool_run_id=tool_run.tool_run_id,
                event_type=TraceEventType.TOOL_STARTED,
                payload={
                    "tool_name": tool_name,
                    "node_name": node_name,
                    "parent_run_id": parent_run_id,
                },
            )
            _store.save_event(started_evt)
            ctx.emit(started_evt)

            try:
                result = _fn(ctx_or_state, *args, **kwargs)

                tool_run.status = RunStatus.SUCCEEDED
                tool_run.ended_at = datetime.now(timezone.utc)
                if tool_run.started_at:
                    tool_run.duration_ms = int(
                        (tool_run.ended_at - tool_run.started_at).total_seconds() * 1000
                    )

                finished_evt = TraceEvent(
                    task_id=task_id,
                    workspace_id=workspace_id,
                    run_id=parent_run_id,
                    tool_run_id=tool_run.tool_run_id,
                    event_type=TraceEventType.TOOL_FINISHED,
                    payload={
                        "tool_name": tool_name,
                        "duration_ms": tool_run.duration_ms,
                    },
                )
                _store.save_event(finished_evt)
                ctx.emit(finished_evt)

                return result

            except Exception as exc:
                tool_run.status = RunStatus.FAILED
                tool_run.ended_at = datetime.now(timezone.utc)
                if tool_run.started_at:
                    tool_run.duration_ms = int(
                        (tool_run.ended_at - tool_run.started_at).total_seconds() * 1000
                    )
                tool_run.error_message = str(exc)

                failed_evt = TraceEvent(
                    task_id=task_id,
                    workspace_id=workspace_id,
                    run_id=parent_run_id,
                    tool_run_id=tool_run.tool_run_id,
                    event_type=TraceEventType.TOOL_FAILED,
                    payload={
                        "tool_name": tool_name,
                        "error": str(exc),
                        "duration_ms": tool_run.duration_ms,
                    },
                )
                _store.save_event(failed_evt)
                ctx.emit(failed_evt)

                raise

        return wrapper

    return decorator


# ─── Context manager helpers ───────────────────────────────────────────────────


@contextmanager
def trace_block(
    name: str,
    ctx: TraceContext,
    event_type: TraceEventType = TraceEventType.WARNING,
    store: InMemoryTraceStore | None = None,
):
    """
    代码块级别的 trace。

    用于记录节点内部某个关键步骤的执行。

    用法：
        with trace_block("chunking", ctx, event_type=TraceEventType.NODE_STARTED):
            chunks = chunk_paper(doc)
    """
    _store = store or _trace_store
    started_at = datetime.now(timezone.utc)

    evt = TraceEvent(
        task_id=ctx.task_id,
        workspace_id=ctx.workspace_id,
        event_type=event_type,
        payload={"block": name, "action": "entered"},
    )
    _store.save_event(evt)
    ctx.emit(evt)

    try:
        yield
    finally:
        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        exit_evt = TraceEvent(
            task_id=ctx.task_id,
            workspace_id=ctx.workspace_id,
            event_type=event_type,
            payload={"block": name, "action": "exited", "duration_ms": duration_ms},
        )
        _store.save_event(exit_evt)
        ctx.emit(exit_evt)

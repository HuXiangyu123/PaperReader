"""工具运行时（Tool Registry）。"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypedDict

from src.tools.specs import ToolSpec, get_tool_spec, register_tool

logger = logging.getLogger(__name__)


class ToolResult(TypedDict):
    """工具调用结果的统一结构。"""

    ok: bool
    output: str | None
    error: str | None
    tool_name: str
    latency_ms: float | None


class ToolRuntime:
    """全局工具注册表 + 调用入口。"""

    def __init__(self) -> None:
        self._functions: dict[str, Callable[..., Any]] = {}

    def register_function(
        self, name: str, func: Callable[..., Any], spec: ToolSpec
    ) -> None:
        self._functions[name] = func
        register_tool(spec)
        logger.info("Tool registered: %s (%s)", name, spec.category)

    def invoke(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """同步调用工具并返回统一结果结构。"""
        import time

        t0 = time.monotonic()
        try:
            func = self._functions.get(tool_name)
            if func is None:
                return ToolResult(
                    ok=False,
                    output=None,
                    error=f"Unknown tool: {tool_name}",
                    tool_name=tool_name,
                    latency_ms=None,
                )
            result = func(**kwargs)
            return ToolResult(
                ok=True,
                output=str(result) if result is not None else "",
                error=None,
                tool_name=tool_name,
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tool %s raised: %s", tool_name, exc)
            return ToolResult(
                ok=False,
                output=None,
                error=f"{type(exc).__name__}: {exc}",
                tool_name=tool_name,
                latency_ms=round((time.monotonic() - t0) * 1000, 1),
            )

    def list_registered(self) -> list[str]:
        return list(self._functions.keys())


# 全局单例
_runtime: ToolRuntime | None = None


def get_runtime() -> ToolRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ToolRuntime()
    return _runtime

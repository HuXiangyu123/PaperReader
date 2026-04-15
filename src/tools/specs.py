"""Tool 接口规范（ToolSpec 定义）。"""

from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """统一工具接口规范。"""

    name: str = Field(..., description="工具唯一名称（snake_case）")
    description: str = Field(..., description="工具用途描述（供 LLM 理解何时调用）")
    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema 格式的输入参数定义"
    )
    category: Literal[
        "search", "metadata", "query_rewrite", "analysis", "utility"
    ] = Field(
        default="utility", description="工具类别"
    )
    cost_hint: str = Field(
        default="unknown", description="资源消耗提示（low/medium/high/unknown）"
    )

    def to_langchain_schema(self) -> dict[str, Any]:
        """转换为 LangChain 兼容的 tool schema 格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema,
        }


TOOL_CATALOG: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> None:
    """注册工具到全局目录。"""
    TOOL_CATALOG[spec.name] = spec


def get_tool_spec(name: str) -> ToolSpec | None:
    return TOOL_CATALOG.get(name)


def list_tools() -> list[ToolSpec]:
    return list(TOOL_CATALOG.values())

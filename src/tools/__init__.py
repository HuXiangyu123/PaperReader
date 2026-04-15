"""工具包 — 统一导出所有工具。"""

from src.tools.local_fs import read_local_file, search_local_files
from src.tools.rag_search import rag_search

# SearchPlanAgent planning tools (SearXNG)
from src.tools.search_tools import (
    detect_sparse_or_noisy_queries,
    expand_keywords,
    merge_duplicate_queries,
    rewrite_query,
    search_arxiv,
    search_local_corpus,
    search_metadata_only,
    summarize_hits,
    estimate_subquestion_coverage,
)

# Tool Runtime
from src.tools.registry import ToolRuntime, get_runtime
from src.tools.specs import ToolSpec, get_tool_spec, list_tools, register_tool

__all__ = [
    # 文件工具
    "read_local_file",
    "search_local_files",
    # RAG 搜索
    "rag_search",
    # 规划工具（SearXNG）
    "search_arxiv",
    "search_local_corpus",
    "search_metadata_only",
    "expand_keywords",
    "rewrite_query",
    "merge_duplicate_queries",
    "summarize_hits",
    "estimate_subquestion_coverage",
    "detect_sparse_or_noisy_queries",
    # Tool Runtime
    "ToolRuntime",
    "ToolSpec",
    "get_runtime",
    "get_tool_spec",
    "list_tools",
    "register_tool",
]

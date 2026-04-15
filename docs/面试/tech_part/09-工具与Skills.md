# PaperReader Agent — 工具与 Skills 体系

---

## 1. 工具层架构

### 1.1 工具分类

```
src/tools/
├── registry.py           # ToolRuntime 全局注册表
├── specs.py              # ToolSpec 定义
├── search_tools.py       # SearXNG wrapper
├── arxiv_api.py          # arXiv API wrapper
├── deepxiv_client.py     # DeepXiv API client
├── rag_search.py         # 本地 RAG search
├── web_fetch.py          # 网页抓取
├── pdf.py                # PDF 解析
├── local_fs.py           # 本地文件操作
└── mcp_adapter.py        # MCP Client Adapter
```

### 1.2 ToolRuntime 注册机制

**文件**：`src/tools/registry.py`

```python
class ToolRuntime:
    """
    全局工具注册表：

    提供统一的工具注册、调用、列表功能。
    所有工具通过 register_function 注册后，可通过 invoke 统一调用。
    """

    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}
        self._functions: dict[str, Callable] = {}

    def register_function(
        self,
        name: str,
        func: Callable,
        spec: ToolSpec,
    ) -> None:
        """注册工具函数"""
        self._tools[name] = spec
        self._functions[name] = func

    def invoke(self, tool_name: str, **kwargs) -> ToolResult:
        """
        统一调用接口：

        - 捕获异常，返回 ToolResult(ok=False, error=...)
        - 记录 latency_ms
        - ToolResult 是所有工具的标准化返回值
        """
        if tool_name not in self._functions:
            return ToolResult(ok=False, error=f"Tool {tool_name} not found")

        func = self._functions[tool_name]
        start = time.monotonic()

        try:
            result = func(**kwargs)
            latency_ms = (time.monotonic() - start) * 1000
            return ToolResult(ok=True, output=result, tool_name=tool_name, latency_ms=latency_ms)
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning(f"[ToolRuntime] {tool_name} failed: {e}")
            return ToolResult(ok=False, error=str(e), tool_name=tool_name, latency_ms=latency_ms)

    def list_registered(self) -> list[str]:
        """列出所有已注册工具"""
        return list(self._tools.keys())


# 全局单例
_runtime: ToolRuntime | None = None

def get_runtime() -> ToolRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ToolRuntime()
    return _runtime
```

**ToolSpec 定义**（`src/tools/specs.py`）：

```python
@dataclass
class ToolSpec:
    """工具规格：名称/描述/分类/输入 Schema"""
    name: str
    description: str
    category: str  # "search" | "fetch" | "parse" | "rag"
    input_schema: dict  # JSON Schema


@dataclass
class ToolResult:
    """标准化返回值：ok / output / error / tool_name / latency_ms"""
    ok: bool
    output: Any | None = None
    error: str | None = None
    tool_name: str | None = None
    latency_ms: float | None = None
```

---

## 2. 核心工具详解

### 2.1 SearXNG Search

**文件**：`src/tools/search_tools.py`

```python
@tool
def _searxng_search(query: str, engines: list[str] | None = None) -> list[dict]:
    """
    SearXNG 搜索工具：

    使用方式：
        results = _searxng_search("large language model", engines=["arxiv"])

    返回格式：
        [{
            "url": "https://arxiv.org/abs/...",
            "title": "...",
            "content": "...",
            "source": "searxng",
        }]
    """
    base_url = settings.searxng_base_url
    params = {
        "q": query,
        "engines": engines or ["arxiv"],
        "format": "json",
    }
    response = httpx.get(f"{base_url}/search", params=params, timeout=15.0)
    data = response.json()
    return [
        {
            "url": r.get("url"),
            "title": r.get("title"),
            "content": r.get("content"),
            "source": "searxng",
        }
        for r in data.get("results", [])
    ]


@tool
def summarize_hits(results: str) -> str:
    """
    对搜索结果做摘要归纳：

    返回结构化 JSON：
    {
        "covered_topics": [...],
        "high_quality_hits": [...],
        "low_quality_hits": [...],
        "missing_angles": [...]
    }
    """
    llm = build_quick_llm(settings)
    prompt = (
        f"以下是搜索结果：\n{results}\n\n"
        "请对上述搜索结果进行摘要分析，输出 JSON：\n"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content
```

### 2.2 arXiv API

**文件**：`src/tools/arxiv_api.py`

```python
def search_arxiv_direct(query: str, max_results: int = 10) -> list[dict]:
    """
    arXiv API 直连搜索：

    特点：
    - 无需 API key（公共 API）
    - 支持多种查询语法（all:, ti:, au:, abs:）
    - 返回完整元数据（authors, categories, abstract）
    """
    import feedparser
    from urllib.parse import urlencode

    url = f"http://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
    }

    feed = feedparser.parse(f"{url}?{urlencode(params)}")

    results = []
    for entry in feed.entries:
        arxiv_id = entry.id.split("/")[-1]
        results.append({
            "arxiv_id": arxiv_id,
            "title": entry.title.strip().replace("\n", " "),
            "authors": [a.name for a in entry.authors],
            "abstract": entry.summary.strip(),
            "published": entry.published,
            "categories": [t.term for t in entry.tags],
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        })
    return results


def fetch_arxiv_paper_by_id(arxiv_id: str) -> dict | None:
    """根据 arXiv ID 获取单篇论文详情"""
    import feedparser

    url = f"http://export.arxiv.org/api/query"
    params = {"id_list": arxiv_id}

    feed = feedparser.parse(f"{url}?{urlencode(params)}")
    if not feed.entries:
        return None

    entry = feed.entries[0]
    return {
        "arxiv_id": arxiv_id,
        "title": entry.title,
        "authors": [a.name for a in entry.authors],
        "abstract": entry.summary,
        "published": entry.published,
        "pdf_url": entry.links[-1].href if entry.links else None,
    }
```

---

## 3. Skills 框架

### 3.1 SkillsRegistry — 四种 Backend Handler

**文件**：`src/skills/registry.py`

```python
class SkillsRegistry:
    """
    Skills 注册中心：支持 4 种 backend 类型

    1. LOCAL_FUNCTION：直接调用 Python 函数
    2. LOCAL_GRAPH：调用 LangGraph 节点函数
    3. MCP_TOOLCHAIN：通过 MCP adapter 调用外部工具
    4. MCP_PROMPT：通过 MCP 获取 prompt
    """

    BACKEND_HANDLERS = {
        SkillBackend.LOCAL_FUNCTION: LocalFunctionHandler(),
        SkillBackend.LOCAL_GRAPH: LocalGraphHandler(),
        SkillBackend.MCP_TOOLCHAIN: MCPToolchainHandler(),
        SkillBackend.MCP_PROMPT: MCPPromptHandler(),
    }

    def get_handler(self, backend: SkillBackend) -> SkillHandler:
        return self.BACKEND_HANDLERS.get(backend)

    async def execute_skill(
        self,
        manifest: SkillManifest,
        inputs: dict,
    ) -> SkillRunResponse:
        handler = self.get_handler(manifest.backend)
        result = await handler.execute(manifest, inputs)
        return result
```

### 3.2 内置 Skills

| Skill ID | 名称 | Backend | 默认 Agent | 用途 |
|----------|------|---------|-----------|------|
| `lit_review_scanner` | Literature Review Scanner | LOCAL_FUNCTION | RETRIEVER | 批量文献扫描 |
| `paper_plan_builder` | Paper Plan Builder | LOCAL_FUNCTION | ANALYST | 生成论文解读计划 |
| `creative_reframe` | Creative Reframe | LOCAL_FUNCTION | PLANNER | 创意性重构主题 |
| `workspace_policy_skill` | Workspace Policy Skill | LOCAL_FUNCTION | SUPERVISOR | 工作区策略管理 |
| `claim_verification` | Claim Verification | LOCAL_FUNCTION | REVIEWER | Claim 验证 |
| `comparison_matrix_builder` | Comparison Matrix Builder | LOCAL_FUNCTION | ANALYST | 构建对比矩阵 |
| `experiment_replicator` | Experiment Replicator | LOCAL_FUNCTION | ANALYST | 实验复现 |
| `writing_scaffold_generator` | Writing Scaffold Generator | LOCAL_FUNCTION | ANALYST | 生成写作大纲 |
| `research_lit_scan` | Research Literature Scan | LOCAL_FUNCTION | RETRIEVER | 学术文献调研 |

### 3.3 SkillOrchestrator — Explicit / Implicit 模式

**文件**：`src/skills/orchestrator.py`

```python
class SkillOrchestrator:
    """
    Skill 编排器：支持 explicit 和 implicit 两种调用模式

    Explicit 模式：用户显式调用 /skill_id args
    Implicit 模式：LLM 自主决定使用哪些 skill
    """

    async def orchestrate(
        self,
        task: str,
        mode: str = "explicit",  # "explicit" | "implicit"
        agent: AgentRole | None = None,
    ) -> list[SkillRunResponse]:
        if mode == "explicit":
            return await self._explicit_invoke(task)
        else:
            # LLM 自主决定 skill chain
            plan = await self._llm_decide_skill_chain(task, agent)
            return await self._execute_skill_chain(plan)
```

---

## 4. Skill 实现示例：Comparison Matrix Builder

**文件**：`src/skills/research_skills.py`

```python
def comparison_matrix_builder(inputs: dict, context: dict) -> dict:
    """
    构建论文对比矩阵：

    输入：
        {
            "paper_cards": [...],  # PaperCard 列表
            "compare_dimensions": ["methods", "datasets", "benchmarks"],
            "format": "json"
        }

    输出：
        {
            "rows": [
                {
                    "paper": "Paper Title",
                    "methods": "...",
                    "datasets": "...",
                    "benchmarks": "...",
                    "limitations": "..."
                }
            ],
            "compression_ratio": 0.87  # 从 30k chars → 4k chars
        }
    """

    paper_cards = inputs["paper_cards"]
    dimensions = inputs.get("compare_dimensions", ["methods", "datasets", "benchmarks"])

    # 渲染论文卡片文本
    cards_text = _render_cards_for_matrix(paper_cards)

    # LLM 生成结构化矩阵
    llm = build_reason_llm(settings, max_tokens=16384)
    prompt = (
        "你是一个学术论文对比分析专家。\n"
        f"以下是 {len(paper_cards)} 篇论文的信息：\n\n"
        f"{cards_text}\n\n"
        "请生成 JSON 对比矩阵，包含以下维度：" + ", ".join(dimensions)
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    matrix = json.loads(response.content)

    # 计算压缩率
    original_chars = sum(len(c.abstract or "") for c in paper_cards)
    compressed_chars = sum(len(row.get("methods", "") + row.get("datasets", ""))
                         for row in matrix.get("rows", []))
    compression_ratio = 1 - (compressed_chars / original_chars) if original_chars > 0 else 0

    return {
        "rows": matrix.get("rows", []),
        "compression_ratio": compression_ratio,
    }
```

---

## 5. MCP Adapter

**文件**：`src/tools/mcp_adapter.py`

### 5.1 两种 Transport

```python
class StdioTransport(MCPTransport):
    """通过 stdio 与本地 MCP server 通信（subprocess.Popen）"""
    async def start(self) -> None:
        self._proc = subprocess.Popen(
            [self.config.command] + self.config.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    async def send(self, method: str, params: dict | None = None) -> dict:
        """JSON-RPC over stdin/stdout"""
        request = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params or {}}
        self._proc.stdin.write(json.dumps(request).encode() + b"\n")
        self._proc.stdin.flush()
        response = json.loads(self._proc.stdout.readline())
        return response.get("result", {})


class RemoteHttpTransport(MCPTransport):
    """通过 HTTP 与远程 MCP server 通信"""
    async def send(self, method: str, params: dict | None = None) -> dict:
        """JSON-RPC over HTTP POST"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.config.base_url}/mcp",
                json={"method": method, "params": params or {}},
            )
            return response.json().get("result", {})
```

### 5.2 MCP 数据模型

**文件**：`src/models/mcp.py`

```python
class MCPServerConfig(BaseModel):
    name: str
    transport: MCPServerTransport  # stdio | http
    command: str | None = None
    args: list[str] = []
    base_url: str | None = None
    env: dict[str, str] = {}


class MCPToolDescriptor(BaseModel):
    name: str
    description: str
    input_schema: dict  # JSON Schema
    annotations: dict | None = None


class MCPInvocationRequest(BaseModel):
    server_name: str
    tool_name: str
    arguments: dict
    invoke_kind: MCPInvokeKind  # call | list_tools | list_prompts | list_resources
```

---

## 6. 技术优势总结

| 优势 | 实现方式 |
|------|---------|
| **工具统一返回** | ToolResult 标准化所有工具返回值 |
| **4 种 Skill Backend** | LOCAL_FUNCTION / LOCAL_GRAPH / MCP_TOOLCHAIN / MCP_PROMPT |
| **MCP 完整实现** | Stdio + HTTP 两种 transport，标准 JSON-RPC |
| **Skill 发现机制** | 扫描 `.agents/skills/` 目录，解析 SKILL.md |
| **Explicit + Implicit 调用** | 显式命令 vs LLM 自主决策 |

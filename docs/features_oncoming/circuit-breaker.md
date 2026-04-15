# Agent 系统熔断机制设计

> 生成时间：2026-04-12
> 状态：**已实现 Phase 1-5**
> 优先级：P1

---

## 实现状态

| Phase | 内容 | 状态 | 文件 |
|-------|------|------|------|
| Phase 1 | `CircuitBreaker` 核心 + 全局注册表 | **✅ 完成** | `src/agent/circuit_breaker.py` |
| Phase 2 | LLM 调用层集成（invoke/ainvoke 包装） | **✅ 完成** | `src/agent/llm.py` |
| Phase 3 | SearXNG/arXiv 集成（`search_tools.py`, `arxiv_api.py`） | **✅ 完成** | `src/tools/search_tools.py`, `src/tools/arxiv_api.py` |
| Phase 4 | Agent Loop 感知熔断，提前终止无效迭代 | **✅ 完成** | `src/research/agents/search_plan_agent.py` |
| Phase 5 | `/circuit-breakers` API + `/circuit-breakers/reset` | **✅ 完成** | `src/api/routes/agents.py` |

---

## 一、背景

当前 agent 系统没有任何熔断机制，存在以下脆弱性：

### 现有容错能力

| 层面 | 现有机制 | 效果 |
|------|---------|------|
| LLM 调用 | `timeout_s=45s`，`max_retries=1` | 超时重试 1 次 |
| SearXNG 搜索 | `timeout=15s`，无重试 | 超时直接抛异常 |
| arXiv API | `timeout=20s/60s`，无重试 | 超时直接抛异常 |
| 外部下载 | `timeout=30s`，无重试 | 超时直接抛异常 |
| Agent 内部异常 | `except: logger.warning(...)` | 静默吞掉，不上报 |

### 当前问题

1. **异常静默吞掉**：所有 `except` 块只打印 `logger.warning`，agent 继续执行，最终产出垃圾结果（如 Q2 搜索不相关的问题）
2. **无失败率追踪**：LLM/搜索 API 连续失败时，系统不知道降级，继续往无效路径上浪费资源
3. **无超时级联**：一个 agent 慢拖累整个 graph
4. **无故障感知**：前几次失败后没有状态积累，下一次调用无法感知"这个 API 目前不健康"

---

## 二、需要熔断的调用链路

```
用户请求
    ↓
┌─────────────────────────────────────────────────────────────┐
│ Supervisor / ResearchGraph                                   │
│  clarify → search_plan → [search] → [extract] → draft      │
│       → review → persist                                    │
└─────────────────────────────────────────────────────────────┘
    ↓
每个节点内部均有三层调用：
┌──────────┐    ┌──────────────────┐    ┌──────────────────┐
│ LLM 调用 │ → │ 外部工具调用      │ → │ 内部 Agent Loop    │
│ (Reason/ │    │ (SearXNG/arXiv/ │    │ (多轮迭代/重试)   │
│  Quick)  │    │  Corpus Search)  │    │                  │
└──────────┘    └──────────────────┘    └──────────────────┘
    ↓               ↓                      ↓
 熔断点 A         熔断点 B              熔断点 C
```

### 熔断点 A：LLM 调用

| 调用方 | LLM 类型 | 超时 | 重试 | 当前异常处理 |
|--------|---------|------|------|------------|
| ClarifyAgent | `build_reason_llm()` | 45s | 1次 | `except: warning` |
| SearchPlanAgent | `build_quick_llm()` | 45s | 1次 | `except: warning` |
| ReviewerAgent | `build_reason_llm()` | 45s | 1次 | `except: warning` |
| RetrieverAgent | `build_reason_llm()` | 45s | 1次 | `except: warning` |
| AnalystAgent | `build_reason_llm()` | 45s | 1次 | `except: warning` |

**故障模式**：
- 模型提供商 API 降级（响应慢 → 超时 → 重试 → 再次超时）
- API Key 超额或限流（429 Too Many Requests）
- 网络抖动导致间歇性超时

### 熔断点 B：外部工具调用

| 调用方 | 工具 | 超时 | 异常处理 |
|--------|------|------|---------|
| SearchPlanAgent | `search_arxiv()` | 20s | `except: warning` |
| SearchPlanAgent | `expand_keywords()` | — | `except: warning` |
| RetrieverAgent | `_searxng_search()` | 15s | 无重试 |
| PlannerAgent | `_searxng_search()` | 15s | `except: warning` |
| 各类 Loader | HTTP 下载 | 30s | 无重试 |

**故障模式**：
- SearXNG 服务宕机（超时 → 静默失败 → 搜索结果为空）
- arXiv API 限流（503 → 返回错误结果）
- 网络不可达（连接超时 → 静默失败）

### 熔断点 C：Agent Loop 内部迭代

| Agent | 迭代次数 | 故障处理 |
|-------|---------|---------|
| SearchPlanAgent | 最多 3 轮 | `except: 跳过本次迭代，继续下一轮` |
| ReviewerAgent | 最多 3 轮 | `except: 跳过本次 review，继续` |
| PlannerAgent | 最多 N 轮 | `except: warning，继续` |

**故障模式**：
- Agent Loop 某轮失败后，下一轮继续调用同一个已知不健康的 API，浪费 token
- 多次失败后仍不放弃，持续消耗 LLM quota

---

## 三、熔断器设计

### 3.1 熔断器类型选择

#### 选项 A：逐 API Key 熔断器（推荐）

每个 `provider + model + endpoint` 组合维护独立熔断器：

```python
# 每个 provider 独立熔断
circuit_breakers = {
    ("openai", "gpt-4o"): CircuitBreaker(failure_threshold=5, timeout=60s),
    ("openai", "gpt-5.4"): CircuitBreaker(failure_threshold=5, timeout=60s),
    ("qwen", "text-embedding-v4"): CircuitBreaker(failure_threshold=3, timeout=30s),
    ("searxng", None): CircuitBreaker(failure_threshold=3, timeout=60s),
    ("arxiv", None): CircuitBreaker(failure_threshold=5, timeout=120s),
}
```

**优点**：精细控制，不同 API 独立熔断
**缺点**：需要管理多个熔断器实例

#### 选项 B：全局单熔断器

整个 agent 系统共享一个熔断器，任何 API 失败都触发全局熔断。

**缺点**：过于粗糙，一个 API 失败导致所有 API 熔断，不推荐。

### 3.2 熔断器状态机

```
            ┌─────────────┐
    ┌──────→│   CLOSED   │←────────────┐
    │       │ (正常调用)  │             │
    │       └─────┬───────┘             │
    │             │ 连续失败 ≥ threshold│  timeout 冷却结束
    │             ▼                    │
    │       ┌─────────────┐            │
    │       │    OPEN     │────────────┘
    │       │ (熔断中)    │   半开状态正常
    │       └─────┬───────┘
    │             │ 冷却时间到，放行 1 个测试请求
    │             ▼
    │       ┌─────────────┐
    └───────│ HALF_OPEN   │───测试成功──→ CLOSED
            │ (放行测试)  │───测试失败──→ OPEN
            └─────────────┘
```

**关键参数**：

| 参数 | LLM (Reason) | LLM (Quick) | SearXNG | arXiv | Embedding |
|------|-------------|------------|---------|-------|-----------|
| `failure_threshold` | 5 次 | 5 次 | 3 次 | 5 次 | 3 次 |
| `timeout` (熔断持续) | 60s | 60s | 60s | 120s | 30s |
| `half_open_max_calls` | 1 | 1 | 1 | 1 | 1 |
| `success_threshold` (半开→关闭) | 1 | 1 | 1 | 1 | 1 |

### 3.3 降级策略

当熔断器打开时，系统应执行降级：

| API | 降级行为 | 影响范围 |
|-----|---------|---------|
| LLM (Reason) | 返回错误，要求用户重试或切换模型 | 整个 graph 暂停 |
| LLM (Quick) | 降级到 `REASON_MODEL`（后者若也熔断则返回错误） | search_plan / extract 降级 |
| SearXNG | 降级到 `search_arxiv_direct()` arXiv 直连 | 搜索功能降级 |
| arXiv 直连 | 降级到本地 corpus 搜索（BM25） | 仅论文元数据 |
| Embedding API | 降级到本地 SentenceTransformer | chunk 检索降级 |
| 网页下载 | 返回错误，不阻塞 graph | 单文档跳过 |

---

## 四、实现方案

### 4.1 熔断器核心实现

**文件**：`src/agent/circuit_breaker.py`（新建）

```python
"""熔断器实现 — 保护 agent 系统免受级联故障影响。"""

from __future__ import annotations

import threading
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"      # 正常：请求通过
    OPEN = "open"           # 熔断：请求被拒绝或返回降级值
    HALF_OPEN = "half_open"  # 半开：放行测试请求


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5       # 连续失败多少次后打开熔断器
    timeout_s: float = 60.0          # 熔断器打开后多少秒进入半开状态
    half_open_max_calls: int = 1     # 半开状态下最多放行多少个测试请求
    success_threshold: int = 1       # 半开状态下成功多少次才关闭熔断器


class CircuitBreaker:
    """
    熔断器：保护外部调用免受级联故障影响。

    状态转换：
    CLOSED → OPEN：连续失败达到 failure_threshold
    OPEN → HALF_OPEN：timeout_s 冷却时间结束
    HALF_OPEN → CLOSED：成功率达到 success_threshold
    HALF_OPEN → OPEN：任何一个测试请求失败
    """

    def __init__(self, key: str, config: CircuitBreakerConfig):
        self.key = key
        self.config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                # 检查冷却时间
                if self._last_failure_time is not None:
                    elapsed = time.monotonic() - self._last_failure_time
                    if elapsed >= self.config.timeout_s:
                        self._state = CircuitState.HALF_OPEN
                        self._half_open_calls = 0
                        logger.info(f"[CircuitBreaker] {self.key} OPEN → HALF_OPEN")
            return self._state

    def can_execute(self) -> bool:
        """判断是否可以执行请求。"""
        s = self.state
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.OPEN:
            return False
        # HALF_OPEN
        with self._lock:
            return self._half_open_calls < self.config.half_open_max_calls

    def record_success(self) -> None:
        """记录一次成功调用。"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info(f"[CircuitBreaker] {self.key} HALF_OPEN → CLOSED")
            else:
                self._failure_count = 0

    def record_failure(self) -> None:
        """记录一次失败调用。"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
                self._success_count = 0
                logger.warning(f"[CircuitBreaker] {self.key} HALF_OPEN → OPEN (test failed)")
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        f"[CircuitBreaker] {self.key} CLOSED → OPEN "
                        f"(failures={self._failure_count})"
                    )

    def execute(
        self,
        func: Callable[..., T],
        fallback: Callable[[], T] | T | None = None,
        *args,
        **kwargs,
    ) -> T:
        """
        通过熔断器执行调用。

        Args:
            func: 要执行的函数
            fallback: 熔断打开时的降级函数（可选）
            *args, **kwargs: 传递给 func 的参数

        Returns:
            func() 的结果，或 fallback() 的结果
        """
        if not self.can_execute():
            if fallback is not None:
                logger.warning(f"[CircuitBreaker] {self.key} is OPEN, using fallback")
                if callable(fallback):
                    return fallback()
                return fallback
            raise CircuitOpenError(f"Circuit breaker '{self.key}' is OPEN")

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure()
            if fallback is not None:
                logger.warning(
                    f"[CircuitBreaker] {self.key} call failed ({exc}), "
                    f"using fallback"
                )
                if callable(fallback):
                    return fallback()
                return fallback
            raise


class CircuitOpenError(Exception):
    """熔断器打开时抛出的异常。"""
    pass
```

### 4.2 全局熔断器注册表

**文件**：`src/agent/circuit_breaker.py`（续）

```python
# ---------------------------------------------------------------------------
# 全局熔断器注册表
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class BreakerSpec:
    """熔断器规格。"""
    key: str
    config: CircuitBreakerConfig


# 全局注册表
_BREAKER_REGISTRY: dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = threading.Lock()


def get_breaker(
    provider: str,
    model: str | None = None,
    endpoint: str | None = None,
) -> CircuitBreaker:
    """
    获取或创建指定 provider 的熔断器。

    key 格式："{provider}" 或 "{provider}/{model}" 或 "{provider}/{model}/{endpoint}"
    """
    key_parts = [provider]
    if model:
        key_parts.append(model)
    if endpoint:
        key_parts.append(endpoint)
    key = "/".join(key_parts)

    with _REGISTRY_LOCK:
        if key not in _BREAKER_REGISTRY:
            config = _DEFAULT_CONFIGS.get(key, CircuitBreakerConfig())
            _BREAKER_REGISTRY[key] = CircuitBreaker(key=key, config=config)
        return _BREAKER_REGISTRY[key]


# 默认配置（按 API 类型）
_DEFAULT_CONFIGS: dict[str, CircuitBreakerConfig] = {
    "openai/gpt-4o": CircuitBreakerConfig(failure_threshold=5, timeout_s=60),
    "openai/gpt-5.4": CircuitBreakerConfig(failure_threshold=5, timeout_s=60),
    "openai/gpt-5.1-codex-mini": CircuitBreakerConfig(failure_threshold=5, timeout_s=60),
    "qwen/text-embedding-v4": CircuitBreakerConfig(failure_threshold=3, timeout_s=30),
    "searxng": CircuitBreakerConfig(failure_threshold=3, timeout_s=60),
    "arxiv": CircuitBreakerConfig(failure_threshold=5, timeout_s=120),
    "arxiv/direct": CircuitBreakerConfig(failure_threshold=5, timeout_s=180),
    "http/download": CircuitBreakerConfig(failure_threshold=3, timeout_s=30),
}


def get_all_breaker_status() -> dict[str, dict]:
    """获取所有熔断器当前状态（用于监控）。"""
    with _REGISTRY_LOCK:
        return {
            key: {
                "state": cb.state.value,
                "failure_count": cb._failure_count,
                "success_count": cb._success_count,
            }
            for key, cb in _BREAKER_REGISTRY.items()
        }


def reset_breaker(key: str) -> None:
    """重置指定熔断器（用于测试或人工干预）。"""
    with _REGISTRY_LOCK:
        if key in _BREAKER_REGISTRY:
            _BREAKER_REGISTRY[key]._state = CircuitState.CLOSED
            _BREAKER_REGISTRY[key]._failure_count = 0
            _BREAKER_REGISTRY[key]._success_count = 0
            logger.info(f"[CircuitBreaker] {key} manually reset to CLOSED")
```

### 4.3 LLM 调用集成

**文件**：`src/agent/llm.py`（修改）

```python
# 在 build_reason_llm / build_quick_llm 中集成熔断器

def build_reason_llm(
    settings,
    timeout_s: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> "ChatAnthropic":
    # ... 现有逻辑 ...

    # 新增：包装 LLM 调用，集成熔断器
    from src.agent.circuit_breaker import get_breaker, CircuitOpenError

    # 解析 provider
    provider = settings.llm_provider or "openai"

    # 获取当前模型的熔断器
    model = settings.reason_model or "gpt-4o"
    breaker = get_breaker(provider, model)

    # 包装 invoke 方法
    original_invoke = llm.invoke

    def wrapped_invoke(messages, **kwargs):
        def _do_invoke():
            return original_invoke(messages, **kwargs)

        fallback_result = _build_fallback_response(
            f"LLM {provider}/{model} circuit is open"
        )
        return breaker.execute(_do_invoke, fallback=lambda: fallback_result)

    llm.invoke = wrapped_invoke

    # 同样包装 ainvoke（异步）
    if hasattr(llm, "ainvoke"):
        original_ainvoke = llm.ainvoke

        async def wrapped_ainvoke(messages, **kwargs):
            async def _do_ainvoke():
                return await original_ainvoke(messages, **kwargs)

            fallback_result = _build_fallback_response(
                f"LLM {provider}/{model} circuit is open"
            )

            if breaker.can_execute():
                try:
                    result = await _do_ainvoke()
                    breaker.record_success()
                    return result
                except Exception as exc:
                    breaker.record_failure()
                    logger.warning(
                        f"[CircuitBreaker] LLM {provider}/{model} failed: {exc}"
                    )
                    return fallback_result
            else:
                logger.warning(
                    f"[CircuitBreaker] LLM {provider}/{model} circuit OPEN, using fallback"
                )
                return fallback_result

        llm.ainvoke = wrapped_ainvoke

    return llm
```

### 4.4 外部工具调用集成

**文件**：`src/tools/search_tools.py`（修改）

```python
# 在 _searxng_search() 中集成熔断器

from src.agent.circuit_breaker import get_breaker, CircuitOpenError

_SEARXNG_BREAKER = get_breaker("searxng")


def _searxng_search_impl(query: str, engines: list[str] | None = None) -> list[dict]:
    """实际的 SearXNG 搜索实现（被熔断器包装）。"""
    # ... 现有逻辑 ...


def _searxng_search_fallback(query: str) -> list[dict]:
    """SearXNG 熔断时的降级：尝试 arXiv 直连搜索。"""
    logger.warning("[SearXNG] Circuit open, falling back to arXiv direct search")
    try:
        from src.tools.arxiv_api import search_arxiv_direct
        return search_arxiv_direct(query, max_results=5)
    except Exception:
        logger.error("[SearXNG] arXiv fallback also failed")
        return []


def _searxng_search(query: str, engines: list[str] | None = None) -> list[dict]:
    """带熔断保护的 SearXNG 搜索。"""
    try:
        return _SEARXNG_BREAKER.execute(
            _searxng_search_impl,
            fallback=lambda: _searxng_search_fallback(query),
            query=query,
            engines=engines,
        )
    except CircuitOpenError:
        logger.error("[SearXNG] Circuit breaker open, no fallback available")
        return []
    except Exception as exc:
        _SEARXNG_BREAKER.record_failure()
        logger.warning(f"[SearXNG] Unexpected error: {exc}")
        return _searxng_search_fallback(query)
```

**文件**：`src/tools/arxiv_api.py`（修改）

```python
from src.agent.circuit_breaker import get_breaker

_ARXIV_BREAKER = get_breaker("arxiv")
_ARXIV_DIRECT_BREAKER = get_breaker("arxiv", "direct")


def fetch_arxiv_papers_by_ids(ids: list[str]) -> list[dict]:
    """带熔断保护的 arXiv ID 获取。"""
    def _do_fetch():
        # ... 现有逻辑 ...

    return _ARXIV_BREAKER.execute(
        _do_fetch,
        fallback=lambda: [],  # 降级：返回空列表，不阻塞 graph
        ids=ids,
    )
```

### 4.5 Agent Loop 层集成

**文件**：`src/research/agents/search_plan_agent.py`（修改）

```python
def run(self, brief, emit_progress, workspace_id, task_id):
    # 新增：检测熔断状态，提前终止无效迭代
    from src.agent.circuit_breaker import get_breaker, get_all_breaker_status

    breaker_status = get_all_breaker_status()
    open_breakers = [k for k, v in breaker_status.items() if v["state"] == "open"]

    if open_breakers:
        logger.warning(
            f"[SearchPlanAgent] Circuit breakers open: {open_breakers}. "
            f"Aborting early to conserve resources."
        )
        return SearchPlanResult(
            query_groups=[],
            papers=[],
            iteration_count=0,
            warnings=["搜索服务暂时不可用，请稍后重试"],
            execution_path="circuit_broken",
        )

    # ... 原有循环逻辑 ...
    for iteration in range(self.max_iterations):
        try:
            # LLM 调用已被熔断器保护
            result = self._invoke_llm(...)
        except CircuitOpenError:
            logger.warning(f"[SearchPlanAgent] Iteration {iteration} LLM circuit open")
            break  # 不要再浪费 token
```

### 4.6 熔断状态暴露（API + 前端）

**文件**：`src/api/routes/agents.py`（新增或修改）

```python
@router.get("/circuit-breakers")
def get_circuit_breaker_status():
    """返回所有熔断器状态（供前端监控面板使用）。"""
    from src.agent.circuit_breaker import get_all_breaker_status
    return get_all_breaker_status()
```

**前端**：在 AgentPanel 或 StatusBar 中显示熔断器状态：

```tsx
// 显示熔断状态徽章
{breakerStates.map(({ key, state }) => (
  <Badge key={key} variant={state === 'open' ? 'destructive' : 'default'}>
    {key}: {state}
  </Badge>
))}
```

---

## 五、监控与告警

### 5.1 日志规范

所有熔断器状态转换必须记录：

```
[CircuitBreaker] openai/gpt-4o CLOSED → OPEN (failures=5)   ← 打开
[CircuitBreaker] openai/gpt-4o OPEN → HALF_OPEN              ← 冷却结束
[CircuitBreaker] openai/gpt-4o HALF_OPEN → CLOSED            ← 恢复
[CircuitBreaker] openai/gpt-4o HALF_OPEN → OPEN (test failed) ← 测试失败
```

### 5.2 SSE 事件

当熔断器打开时，通过 SSE 通知前端：

```
event: circuit_open
data: {"key": "searxng", "message": "搜索服务暂时不可用"}

event: circuit_closed
data: {"key": "searxng", "message": "搜索服务已恢复"}
```

---

## 六、测试计划

| # | 测试场景 | 验证内容 |
|---|---------|---------|
| T1 | 模拟 LLM 连续 5 次超时 | 熔断器从 CLOSED → OPEN |
| T2 | 熔断 OPEN 状态下调用 LLM | 返回 fallback，不再发送请求 |
| T3 | 60s 冷却后 | OPEN → HALF_OPEN |
| T4 | 半开状态测试成功 | HALF_OPEN → CLOSED |
| T5 | 半开状态测试失败 | HALF_OPEN → OPEN，重新冷却 |
| T6 | 两个不同 provider 独立熔断 | 一个 OPEN 不影响另一个 |
| T7 | 降级路径验证 | SearXNG 熔断 → arXiv 直连降级 |
| T8 | Agent Loop 感知熔断 | 检测到 OPEN 后主动终止迭代 |

---

## 七、实现优先级

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | 实现 `CircuitBreaker` 核心 + 全局注册表 | P0 |
| **Phase 2** | LLM 调用层集成熔断（`llm.py` 包装） | P0 |
| **Phase 3** | SearXNG/arXiv 集成熔断（`search_tools.py`） | P0 |
| **Phase 4** | Agent Loop 层感知熔断，提前终止无效迭代 | P1 |
| **Phase 5** | `/circuit-breakers` API + 前端监控面板 | P2 |
| **Phase 6** | 降级策略精细化（根据熔断状态切换不同模型） | P2 |

---

## 八、相关文件清单

| 文件 | 操作 | 备注 |
|------|------|------|
| `src/agent/circuit_breaker.py` | 新建 | 熔断器核心实现 |
| `src/agent/llm.py` | 修改 | 包装 LLM invoke |
| `src/tools/search_tools.py` | 修改 | SearXNG + arXiv 集成 |
| `src/tools/arxiv_api.py` | 修改 | arXiv 调用集成 |
| `src/research/agents/search_plan_agent.py` | 修改 | Agent Loop 感知熔断 |
| `src/research/agents/reviewer_agent.py` | 修改 | Agent Loop 感知熔断 |
| `src/api/routes/agents.py` | 修改 | 新增 `/circuit-breakers` 端点 |
| `frontend/src/components/AgentPanel.tsx` | 修改 | 显示熔断器状态 |

---

## 九、参考设计

- [Circuit Breaker Pattern - Martin Fowler](https://martinfowler.com/bliki/CircuitBreaker.html)
- Python 库 [pybreaker](https://github.com/danielychan/pybreaker)：可考虑直接集成而非重复造轮子
- LangChain [Callbacks](https://python.langchain.com/docs/concepts/callbacks/)：已有 on_llm_error 钩子，可结合使用

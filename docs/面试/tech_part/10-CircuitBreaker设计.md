# PaperReader Agent — Circuit Breaker 熔断器设计

> 本文档基于 `src/agent/circuit_breaker.py` 已实现代码，分析其设计实现。

---

## 1. 为什么需要熔断器

### 1.1 Agent 系统的脆弱性

```
┌─────────────────────────────────────────────────────────────────┐
│                      Agent 系统故障链                              │
│                                                                  │
│  LLM API 限流/宕机                                              │
│       │                                                          │
│       ▼                                                          │
│  调用超时 → 重试 → 再次超时 → 浪费 token → 系统 hang              │
│       │                                                          │
│       ▼                                                          │
│  SearXNG 服务不可用                                              │
│       │                                                          │
│       ▼                                                          │
│  搜索失败 → 返回空结果 → 后续节点拿到空输入 → 产出垃圾结果          │
│       │                                                          │
│       ▼                                                          │
│  异常静默（except: warning）→ 继续执行 → 最终产出不可靠报告        │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 当前系统的容错现状

| 层面 | 现有机制 | 效果 |
|------|---------|------|
| LLM 调用 | `timeout_s=45s`，`max_retries=1` | 超时重试 1 次 |
| SearXNG | `timeout=15s`，无重试 | 超时直接抛异常 |
| arXiv API | `timeout=20s`，无重试 | 超时直接抛异常 |
| 外部下载 | `timeout=30s`，无重试 | 超时直接抛异常 |
| Agent 内部异常 | `except: logger.warning(...)` | 静默吞掉，不上报 |

**核心问题**：
- 异常静默吞掉：agent 继续执行，产出垃圾结果
- 无失败率追踪：连续失败时系统不知道降级
- 无故障感知：前几次失败后没有状态积累

---

## 2. 熔断器核心实现

**文件**：`src/agent/circuit_breaker.py`

### 2.1 状态机

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

### 2.2 核心代码

```python
class CircuitState(Enum):
    CLOSED = "closed"       # 正常：请求通过
    OPEN = "open"            # 熔断：请求被拒绝或返回降级值
    HALF_OPEN = "half_open"  # 半开：放行测试请求


class CircuitBreaker:
    """
    熔断器：保护外部调用免受级联故障影响。
    使用 threading.Lock 保证并发安全。
    """

    def __init__(self, key: str, config: CircuitBreakerConfig | None = None):
        self.key = key
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: float | None = None
        self._lock = threading.Lock()  # 线程安全

    @property
    def state(self) -> CircuitState:
        """检查状态转换（OPEN → HALF_OPEN）"""
        with self._lock:
            if self._state == CircuitState.OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.config.timeout_s:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info(f"[CircuitBreaker] {self.key} OPEN → HALF_OPEN")
            return self._state

    def can_execute(self) -> bool:
        """判断是否可以执行请求"""
        s = self.state
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.OPEN:
            return False
        # HALF_OPEN：只放行有限数量测试请求
        with self._lock:
            return self._half_open_calls < self.config.half_open_max_calls

    def record_success(self) -> None:
        """记录一次成功调用"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info(f"[CircuitBreaker] {self.key} HALF_OPEN → CLOSED")
            else:
                self._failure_count = 0  # 成功则重置计数器

    def record_failure(self) -> None:
        """记录一次失败调用"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN  # 测试失败立即打开
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN

    def execute(
        self,
        func: Callable[..., T],
        fallback: Callable[[], T] | T | None = None,
        *args,
        **kwargs,
    ) -> T:
        """
        通过熔断器执行调用：

        - 熔断打开时返回 fallback（或抛 CircuitOpenError）
        - 正常调用时记录成功/失败
        - 异常时自动熔断
        """
        if not self.can_execute():
            if fallback is not None:
                return fallback() if callable(fallback) else fallback
            raise CircuitOpenError(f"Circuit breaker '{self.key}' is OPEN")

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure()
            if fallback is not None:
                return fallback() if callable(fallback) else fallback
            raise
```

---

## 3. 全局熔断器注册表

### 3.1 按 API Key 独立熔断

```python
# 每个 provider 独立熔断，互不影响
_BREAKER_REGISTRY: dict[str, CircuitBreaker] = {}

def get_breaker(
    provider: str,
    model: str | None = None,
    endpoint: str | None = None,
) -> CircuitBreaker:
    """
    获取或创建指定 provider 的熔断器。

    key 格式："{provider}" 或 "{provider}/{model}"
    """
    key = f"{provider}/{model}" if model else provider

    with _REGISTRY_LOCK:
        if key not in _BREAKER_REGISTRY:
            config = _DEFAULT_CONFIGS.get(key, CircuitBreakerConfig())
            _BREAKER_REGISTRY[key] = CircuitBreaker(key=key, config=config)
        return _BREAKER_REGISTRY[key]


# 默认配置
_DEFAULT_CONFIGS: dict[str, CircuitBreakerConfig] = {
    "openai/gpt-4o": CircuitBreakerConfig(failure_threshold=5, timeout_s=60),
    "openai/gpt-5.4": CircuitBreakerConfig(failure_threshold=5, timeout_s=60),
    "searxng": CircuitBreakerConfig(failure_threshold=3, timeout_s=60),
    "arxiv": CircuitBreakerConfig(failure_threshold=5, timeout_s=120),
    "http/download": CircuitBreakerConfig(failure_threshold=3, timeout_s=30),
}
```

**设计原则**：不同 API 独立熔断，一个服务宕机不影响其他服务。

---

## 4. 降级策略

### 4.1 降级路径

| API | 降级行为 | 影响范围 |
|-----|---------|---------|
| LLM (Reason) | 返回错误，要求用户重试或切换模型 | 整个 graph 暂停 |
| LLM (Quick) | 降级到 REASON_MODEL（后者若也熔断则返回错误） | search_plan / extract 降级 |
| SearXNG | 降级到 `search_arxiv_direct()` arXiv 直连 | 搜索功能降级 |
| arXiv 直连 | 降级到本地 corpus 搜索（BM25） | 仅论文元数据 |
| Embedding API | 降级到本地 SentenceTransformer | chunk 检索降级 |

### 4.2 集成示例

```python
# 在 LLM 调用层集成熔断器
def build_reason_llm_with_circuit_breaker(settings, ...):
    llm = build_reason_llm(settings, ...)
    breaker = get_breaker(settings.llm_provider, settings.reason_model)

    def wrapped_invoke(messages, **kwargs):
        def _do_invoke():
            return llm.invoke(messages, **kwargs)

        fallback_result = _build_fallback_response("LLM circuit is open")
        return breaker.execute(_do_invoke, fallback=lambda: fallback_result)

    llm.invoke = wrapped_invoke
    return llm
```

---

## 5. 熔断器参数设计

### 5.1 参数选择依据

| 参数 | LLM (Reason) | LLM (Quick) | SearXNG | arXiv | Embedding |
|------|-------------|------------|---------|-------|-----------|
| `failure_threshold` | 5 次 | 5 次 | 3 次 | 5 次 | 3 次 |
| `timeout_s` (熔断持续) | 60s | 60s | 60s | 120s | 30s |
| `half_open_max_calls` | 1 | 1 | 1 | 1 | 1 |
| `success_threshold` | 1 | 1 | 1 | 1 | 1 |

**选择理由**：
- `failure_threshold=5`：LLM 失败可能是临时限流，5 次排除偶然因素
- `timeout_s=60`：1 分钟冷却，让服务有恢复时间
- `half_open_max_calls=1`：半开状态只放行 1 个测试请求，避免突发流量

---

## 6. 监控与 API

### 6.1 状态暴露 API

```python
@router.get("/circuit-breakers")
def get_circuit_breaker_status():
    """返回所有熔断器状态"""
    return get_all_breaker_status()


def get_all_breaker_status() -> dict[str, dict]:
    """获取所有熔断器当前状态"""
    return {
        key: {
            "state": cb.state.value,
            "failure_count": cb._failure_count,
            "success_count": cb._success_count,
        }
        for key, cb in _BREAKER_REGISTRY.items()
    }


@router.post("/circuit-breakers/{key}/reset")
def reset_circuit_breaker(key: str):
    """手动重置指定熔断器"""
    reset_breaker(key)
    return {"status": "reset", "key": key}
```

### 6.2 SSE 事件

```python
# 当熔断器打开时，通过 SSE 通知前端
event = {
    "event": "circuit_open",
    "data": {
        "key": "searxng",
        "message": "搜索服务暂时不可用",
        "timestamp": datetime.utcnow().isoformat(),
    }
}
await event_queue.put(event)
```

---

## 7. 测试用例

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

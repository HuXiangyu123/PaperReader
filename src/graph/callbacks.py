from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone


class NodeEventEmitter:
    """Emits node start/end events to an asyncio.Queue for SSE streaming."""

    def __init__(self, queue: asyncio.Queue | None = None):
        self.queue = queue
        self.events: list[dict] = []

    def _emit(self, event: dict):
        self.events.append(event)
        if self.queue:
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def on_node_start(self, node_name: str):
        self._emit({
            "type": "node_start",
            "node": node_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def on_node_end(
        self,
        node_name: str,
        *,
        tokens_delta: int = 0,
        warnings: list[str] | None = None,
        duration_ms: int | None = None,
        status: str = "done",
        error: str | None = None,
    ):
        self._emit({
            "type": "node_end",
            "node": node_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tokens_delta": tokens_delta,
            "warnings": warnings or [],
            "duration_ms": duration_ms,
            "status": status,
            "error": error,
        })

    def on_thinking(self, node_name: str, content: str):
        self._emit({
            "type": "thinking",
            "node": node_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "content": content,
        })

    def to_trace_json(self) -> str:
        return json.dumps(self.events, indent=2, ensure_ascii=False)

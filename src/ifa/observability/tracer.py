# ifa/observability/tracer.py
"""轻量级请求追踪器 — 记录每个 Agent 的执行时间、工具调用和 token 使用。

无需 Langfuse/OpenTelemetry 等外部依赖，日志写入本地 JSON 文件。
可通过配置切换到 Langfuse 或 OTel 等后端。
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TraceSpan:
    """单个 Agent/节点的执行追踪。"""

    def __init__(self, name: str, span_type: str = "agent"):
        self.name = name
        self.span_type = span_type
        self.start_time = time.monotonic()
        self.end_time: float | None = None
        self.status: str = "running"
        self.metadata: dict[str, Any] = {}
        self.error: str | None = None

    def finish(self, status: str = "ok", **metadata):
        """结束追踪。"""
        self.end_time = time.monotonic()
        self.status = status
        self.metadata.update(metadata)

    def fail(self, error: str):
        """标记为失败。"""
        self.end_time = time.monotonic()
        self.status = "error"
        self.error = error

    @property
    def duration_ms(self) -> float:
        """持续时间（毫秒）。"""
        end = self.end_time or time.monotonic()
        return (end - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.span_type,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 1),
            "error": self.error,
            **self.metadata,
        }


class RequestTracer:
    """一次分析请求的完整追踪。"""

    def __init__(self, request_id: str, mode: str, fund_codes: str = ""):
        self.request_id = request_id
        self.mode = mode
        self.fund_codes = fund_codes
        self.created_at = datetime.now().isoformat()
        self.spans: list[TraceSpan] = []
        self._active_span: TraceSpan | None = None

    def start_span(self, name: str, span_type: str = "agent") -> TraceSpan:
        """开始一个新的追踪段。"""
        span = TraceSpan(name, span_type)
        self.spans.append(span)
        self._active_span = span
        return span

    def finish_current(self, status: str = "ok", **metadata):
        """结束当前活跃的追踪段。"""
        if self._active_span and self._active_span.status == "running":
            self._active_span.finish(status, **metadata)
            self._active_span = None

    def fail_current(self, error: str):
        """将当前追踪段标记为失败。"""
        if self._active_span and self._active_span.status == "running":
            self._active_span.fail(error)
            self._active_span = None

    @property
    def total_duration_ms(self) -> float:
        if not self.spans:
            return 0
        first = min(s.start_time for s in self.spans)
        last = max(s.end_time or time.monotonic() for s in self.spans)
        return (last - first) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "mode": self.mode,
            "fund_codes": self.fund_codes,
            "created_at": self.created_at,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "spans": [s.to_dict() for s in self.spans],
        }

    def save(self, output_dir: str = "results"):
        """保存追踪结果到 JSON 文件。"""
        fund_dir = self.fund_codes.replace(",", "_").strip() if self.fund_codes else "unknown"
        path = Path(output_dir) / fund_dir
        path.mkdir(parents=True, exist_ok=True)
        filepath = path / f"{self.request_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.debug("追踪已保存: %s", filepath)
        return str(filepath)

_current_tracer_var: contextvars.ContextVar[RequestTracer | None] = contextvars.ContextVar("ifa_tracer", default=None)


def start_trace(request_id: str, mode: str, fund_codes: str = "") -> RequestTracer:
    """开始一次请求追踪。"""
    tracer = RequestTracer(request_id, mode, fund_codes)
    _current_tracer_var.set(tracer)
    return tracer


def get_current_tracer() -> RequestTracer | None:
    """获取当前请求追踪器（线程安全）。"""
    return _current_tracer_var.get()


def end_trace(output_dir: str = "results") -> str | None:
    """结束并保存当前请求追踪。"""
    tracer = _current_tracer_var.get()
    if tracer is None:
        return None
    path = tracer.save(output_dir)
    _current_tracer_var.set(None)
    return path

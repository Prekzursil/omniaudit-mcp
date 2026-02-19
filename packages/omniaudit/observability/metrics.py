from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

TOOL_CALLS_TOTAL = Counter(
    "omniaudit_tool_calls_total",
    "Total tool calls by tool and status",
    labelnames=("tool", "status"),
)

TOOL_CALL_LATENCY_SECONDS = Histogram(
    "omniaudit_tool_latency_seconds",
    "Tool call latency",
    labelnames=("tool",),
)

WRITE_GATE_DENIED = Counter(
    "omniaudit_write_gate_denied_total",
    "Write operations denied by confirmation gate",
    labelnames=("tool",),
)

RATE_LIMIT_DENIED = Counter(
    "omniaudit_rate_limit_denied_total",
    "Operations denied by rate limiter",
    labelnames=("bucket",),
)


def record_tool_call(tool: str, status: str, duration_seconds: float) -> None:
    TOOL_CALLS_TOTAL.labels(tool=tool, status=status).inc()
    TOOL_CALL_LATENCY_SECONDS.labels(tool=tool).observe(duration_seconds)


def record_write_gate_denied(tool: str) -> None:
    WRITE_GATE_DENIED.labels(tool=tool).inc()


def record_rate_limit_denied(bucket: str) -> None:
    RATE_LIMIT_DENIED.labels(bucket=bucket).inc()


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST

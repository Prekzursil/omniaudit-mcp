from __future__ import annotations

import io
import logging

from omniaudit.observability.logging import JsonLogFormatter
from omniaudit.observability.metrics import (
    RATE_LIMIT_DENIED,
    TOOL_CALLS_TOTAL,
    WRITE_GATE_DENIED,
    record_rate_limit_denied,
    record_tool_call,
    record_write_gate_denied,
)


def test_json_log_formatter_has_required_fields() -> None:
    logger = logging.getLogger("test_json_logger")
    logger.setLevel(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    logger.handlers = [handler]

    logger.info(
        "tool completed",
        extra={
            "request_id": "req_1",
            "tool": "core.health",
            "module_name": "core",
            "duration_ms": 12,
            "status": "success",
        },
    )

    payload = stream.getvalue()
    assert '"request_id": "req_1"' in payload
    assert '"tool": "core.health"' in payload
    assert '"duration_ms": 12' in payload
    assert '"status": "success"' in payload


def test_metrics_counters_increment() -> None:
    tool_before = TOOL_CALLS_TOTAL.labels(tool="core.health", status="success")._value.get()
    write_before = WRITE_GATE_DENIED.labels(tool="auditlens.create_issue")._value.get()
    rate_before = RATE_LIMIT_DENIED.labels(bucket="scan")._value.get()

    record_tool_call("core.health", "success", 0.01)
    record_write_gate_denied("auditlens.create_issue")
    record_rate_limit_denied("scan")

    assert (
        TOOL_CALLS_TOTAL.labels(tool="core.health", status="success")._value.get()
        == tool_before + 1
    )
    assert WRITE_GATE_DENIED.labels(tool="auditlens.create_issue")._value.get() == write_before + 1
    assert RATE_LIMIT_DENIED.labels(bucket="scan")._value.get() == rate_before + 1

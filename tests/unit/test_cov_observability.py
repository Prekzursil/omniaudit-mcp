from __future__ import annotations

import logging

from fastapi import FastAPI
from omniaudit.observability import tracing as tracing_module
from omniaudit.observability.logging import (
    JsonLogFormatter,
    configure_logging,
    request_id_context,
)
from omniaudit.observability.tracing import init_tracing, tracing_initialized


def test_configure_logging_json_and_text() -> None:
    configure_logging("json")  # also exercises the handler-removal branch on re-config
    configure_logging("text")
    root = logging.getLogger()
    assert root.handlers
    # Restore JSON formatting for the rest of the suite.
    configure_logging("json")


def test_configure_logging_with_no_existing_handlers() -> None:
    root = logging.getLogger()
    saved = list(root.handlers)
    for handler in saved:
        root.removeHandler(handler)
    try:
        configure_logging("json")  # no pre-existing handlers -> skips removal loop
        assert root.handlers
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved:
            root.addHandler(handler)
        configure_logging("json")


def test_json_log_formatter_emits_context() -> None:
    token = request_id_context.set("req-123")
    try:
        record = logging.LogRecord("n", logging.INFO, __file__, 1, "hello", None, None)
        payload = JsonLogFormatter().format(record)
    finally:
        request_id_context.reset(token)
    assert '"message": "hello"' in payload
    assert '"request_id": "req-123"' in payload


def test_init_tracing_disabled() -> None:
    app = FastAPI()
    assert init_tracing(app, enabled=False) is False
    assert tracing_initialized() is False


def test_init_tracing_enabled_success() -> None:
    app = FastAPI()
    result = init_tracing(app, enabled=True, otlp_endpoint="http://localhost:4318/v1/traces")
    assert result is True
    assert tracing_initialized() is True


def test_init_tracing_enabled_failure(monkeypatch) -> None:
    # Force the optional import block to raise so the except branch is exercised.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("no otel")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    app = FastAPI()
    assert init_tracing(app, enabled=True) is False
    assert tracing_module.tracing_initialized() is False

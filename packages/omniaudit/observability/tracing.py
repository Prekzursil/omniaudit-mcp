from __future__ import annotations

from fastapi import FastAPI

_TRACING_INITIALIZED = False


def init_tracing(app: FastAPI, enabled: bool, otlp_endpoint: str | None = None) -> bool:
    global _TRACING_INITIALIZED
    if not enabled:
        _TRACING_INITIALIZED = False
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "omniaudit-mcp"})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint) if otlp_endpoint else OTLPSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        _TRACING_INITIALIZED = True
        return True
    except Exception:
        _TRACING_INITIALIZED = False
        return False


def tracing_initialized() -> bool:
    return _TRACING_INITIALIZED

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from omniaudit.core.settings import settings
from omniaudit.mcp.runtime import MCPToolError, build_runtime, call_tool, list_tools
from omniaudit.observability.logging import configure_logging, request_id_context
from omniaudit.observability.metrics import render_metrics
from omniaudit.observability.tracing import init_tracing

configure_logging(settings.log_format)
app = FastAPI(title=settings.app_name, version="0.1.0")
runtime = build_runtime()
init_tracing(
    app,
    enabled=settings.otel_enabled,
    otlp_endpoint=settings.otel_exporter_otlp_endpoint,
)


async def _check_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.mcp_auth_mode != "api_key":
        return
    if not settings.mcp_api_key:
        raise HTTPException(status_code=500, detail="mcp_api_key is not configured")
    if x_api_key != settings.mcp_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.middleware("http")
async def attach_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_context.reset(token)
    response.headers["x-request-id"] = request_id
    return response


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "env": settings.app_env,
    }


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "mcp": "/mcp",
        "ui": "/ui",
    }


@app.get("/ui", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>OmniAudit Dashboard</title>
  <style>
    :root {
      --bg: #0b1018;
      --panel: #121a25;
      --text: #e9eef5;
      --muted: #90a0b5;
      --accent: #2bb673;
      --warn: #e0912d;
    }
    body { margin:0; font-family: ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif; background: linear-gradient(145deg, #0b1018, #111c2a 60%, #102730); color: var(--text); }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(260px,1fr)); gap: 16px; }
    .card { background: color-mix(in srgb, var(--panel) 88%, black); border: 1px solid #223247; border-radius: 12px; padding: 16px; }
    .title { margin: 0 0 8px; font-size: 18px; }
    .muted { color: var(--muted); font-size: 14px; }
    code { background: #0f1622; border: 1px solid #273852; border-radius: 6px; padding: 2px 6px; }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>OmniAudit MCP</h1>
    <p class=\"muted\">AuditLens + SiteLint + Release Butler</p>
    <div class=\"grid\">
      <section class=\"card\"><h2 class=\"title\">FindingsBoard</h2><p class=\"muted\">Use <code>auditlens.*</code> tools for evidence triage and issue creation.</p></section>
      <section class=\"card\"><h2 class=\"title\">JobTimeline</h2><p class=\"muted\">Use <code>sitelint.start_scan</code> and <code>core.get_job</code> for live scan progress.</p></section>
      <section class=\"card\"><h2 class=\"title\">ReleasePanel</h2><p class=\"muted\">Use <code>releasebutler.*</code> tools for assets, checksums, and release notes.</p></section>
    </div>
  </div>
</body>
</html>
    """


@app.get("/ui/state")
def dashboard_state() -> dict[str, Any]:
    jobs = runtime.jobs.list_jobs(limit=25)
    receipts = runtime.receipts.list_receipts()
    return {
        "jobs": [
            {
                "job_id": row.job_id,
                "module": row.module,
                "status": row.status,
                "progress": row.progress,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in jobs
        ],
        "receipts": [
            {
                "receipt_id": row.receipt_id,
                "operation": row.operation,
                "inputs_hash": row.inputs_hash,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "result_ref": row.result_ref,
            }
            for row in receipts[:50]
        ],
    }


@app.get("/metrics")
def metrics() -> Response:
    if not settings.prometheus_enabled:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@app.post("/mcp", dependencies=[Depends(_check_api_key)])
async def mcp_handler(request: Request) -> dict[str, Any]:
    payload = await request.json()
    method = payload.get("method")
    req_id = payload.get("id")

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {
                        "name": settings.app_name,
                        "version": "0.1.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": list_tools(),
            }

        if method == "tools/call":
            params = payload.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not name:
                raise MCPToolError("tools/call requires params.name")
            result = call_tool(
                runtime,
                name=name,
                arguments=arguments,
                request_id=request_id_context.get(),
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": str(result),
                        }
                    ],
                    "structuredContent": result,
                },
            }

        raise MCPToolError(f"Unsupported method: {method}")
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32000,
                "message": str(exc),
            },
        }

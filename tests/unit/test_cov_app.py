from __future__ import annotations

from fastapi.testclient import TestClient
from mcp_server.main import app
from omniaudit.core.settings import settings


def test_healthz_root_ui_and_state() -> None:
    client = TestClient(app)
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/").json()["mcp"] == "/mcp"
    assert "OmniAudit" in client.get("/ui").text
    state = client.get("/ui/state").json()
    assert "jobs" in state and "receipts" in state


def test_metrics_disabled_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(settings, "prometheus_enabled", False)
    client = TestClient(app)
    assert client.get("/metrics").status_code == 404


def test_mcp_requires_name_and_rejects_unknown_method() -> None:
    client = TestClient(app)
    no_name = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"arguments": {}}},
    )
    assert "error" in no_name.json()

    bad_method = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "frobnicate"})
    assert "Unsupported method" in bad_method.json()["error"]["message"]


def test_tool_error_returns_generic_message_not_internal_detail() -> None:
    client = TestClient(app)
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "does.not.exist", "arguments": {}},
        },
    )
    error = resp.json()["error"]
    # Internal exception detail (e.g. "Unknown tool name: ...") must not leak to clients.
    assert error["message"] == "Internal server error"
    assert "Unknown tool" not in error["message"]


def test_api_key_enforcement(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mcp_auth_mode", "api_key")

    # Not configured -> 500.
    monkeypatch.setattr(settings, "mcp_api_key", None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp.status_code == 500

    # Configured but wrong/absent key -> 401.
    monkeypatch.setattr(settings, "mcp_api_key", "secret-key")
    assert (
        client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}).status_code
        == 401
    )

    # Correct key -> 200.
    ok = client.post(
        "/mcp",
        headers={"x-api-key": "secret-key"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert ok.status_code == 200

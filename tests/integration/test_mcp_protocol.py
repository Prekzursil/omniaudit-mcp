from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from mcp_server.main import app


def test_initialize_and_list_tools() -> None:
    client = TestClient(app)

    initialize = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert initialize.status_code == 200
    assert initialize.json()["result"]["serverInfo"]["name"] == "OmniAudit MCP"

    tools = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert tools.status_code == 200
    names = {tool["name"] for tool in tools.json()["result"]["tools"]}
    assert "auditlens.list_runs" in names
    assert "releasebutler.create_release" in names


def test_write_tool_requires_confirmation_token() -> None:
    client = TestClient(app)

    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "auditlens.create_issue",
                "arguments": {
                    "repo": "Prekzursil/AdrianaArt",
                    "title": "test",
                    "body": "test",
                    "labels": ["audit:ux"],
                },
            },
        },
    )

    body = response.json()
    structured = body["result"]["structuredContent"]
    assert structured["requires_confirmation"] is True
    assert structured["risk_level"] == "high"
    assert "confirmation_token" in structured


def test_core_health_includes_observability_block() -> None:
    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "core.health", "arguments": {}},
        },
    )
    structured = response.json()["result"]["structuredContent"]
    assert "observability" in structured
    assert "metrics_enabled" in structured["observability"]
    assert "tracing_initialized" in structured["observability"]


def test_metrics_endpoint_exposes_prometheus_format() -> None:
    client = TestClient(app)
    _ = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "core.health", "arguments": {}},
        },
    )
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "omniaudit_tool_calls_total" in response.text
    assert 'status="success"' in response.text


def test_metrics_include_gate_denied_and_rate_limit_denials() -> None:
    from mcp_server.main import runtime

    client = TestClient(app)

    # Force rate-limit denial for scan submissions in this test.
    original_scan_limit = runtime.scan_rate_limiter.limit_per_minute
    runtime.scan_rate_limiter.limit_per_minute = 0
    try:
        rate_limited = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 12,
                "method": "tools/call",
                "params": {
                    "name": "sitelint.start_scan",
                    "arguments": {
                        "url": "https://example.com",
                        "profile": "standard",
                        "viewport_set": "desktop_mobile",
                    },
                },
            },
        )
        assert "error" in rate_limited.json()
    finally:
        runtime.scan_rate_limiter.limit_per_minute = original_scan_limit

    gate_denied = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "auditlens.create_issue",
                "arguments": {
                    "repo": "Prekzursil/AdrianaArt",
                    "title": "test",
                    "body": "test",
                    "labels": ["audit:ux"],
                },
            },
        },
    )
    assert gate_denied.json()["result"]["structuredContent"]["requires_confirmation"] is True

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "omniaudit_write_gate_denied_total" in metrics.text
    assert 'tool="auditlens.create_issue"' in metrics.text
    assert "omniaudit_rate_limit_denied_total" in metrics.text
    assert 'bucket="scan"' in metrics.text


def test_generate_notes_accepts_from_and_to_tags(monkeypatch) -> None:
    captured = {}

    def fake_generate_notes(
        self,
        repo,
        tag,
        window,
        from_tag,
        to_tag,
        fallback_window,
        group_by=None,
        include_pr_links=False,
    ):
        captured.update(
            {
                "repo": repo,
                "tag": tag,
                "window": window,
                "from_tag": from_tag,
                "to_tag": to_tag,
                "fallback_window": fallback_window,
                "group_by": group_by,
                "include_pr_links": include_pr_links,
            }
        )
        return {
            "notes": "ok",
            "range": {"from_tag": from_tag, "to_tag": to_tag, "fallback_used": False},
        }

    monkeypatch.setattr(
        type(__import__("mcp_server.main", fromlist=["runtime"]).runtime.releasebutler),
        "generate_notes",
        fake_generate_notes,
    )

    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "releasebutler.generate_notes",
                "arguments": {
                    "repo": "Prekzursil/AdrianaArt",
                    "from_tag": "v1.0.0",
                    "to_tag": "v2.0.0",
                    "fallback_window": 15,
                },
            },
        },
    )
    assert response.status_code == 200
    structured = response.json()["result"]["structuredContent"]
    assert structured["range"]["from_tag"] == "v1.0.0"
    assert captured["to_tag"] == "v2.0.0"


def test_create_release_accepts_local_assets_and_returns_metadata(
    monkeypatch, tmp_path: Path
) -> None:
    captured = {}

    def fake_create_release(
        self,
        repo,
        tag,
        notes,
        assets,
        draft=False,
        prerelease=False,
        dry_run=False,
        provenance_manifest=False,
    ):
        captured.update(
            {
                "repo": repo,
                "tag": tag,
                "notes": notes,
                "assets": assets,
                "draft": draft,
                "prerelease": prerelease,
                "dry_run": dry_run,
                "provenance_manifest": provenance_manifest,
            }
        )
        return {
            "repo": repo,
            "tag": tag,
            "release_url": "https://example/release/v3",
            "release_id": 3,
            "assets_requested": assets,
            "uploaded_assets": [
                {
                    "id": 1,
                    "name": "artifact.zip",
                    "size": 11,
                    "download_url": "https://example/download/artifact.zip",
                }
            ],
            "failed_assets": [],
        }

    monkeypatch.setattr(
        type(__import__("mcp_server.main", fromlist=["runtime"]).runtime.releasebutler),
        "create_release",
        fake_create_release,
    )

    asset = tmp_path / "artifact.zip"
    asset.write_bytes(b"zip-content")

    client = TestClient(app)
    initial = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": "releasebutler.create_release",
                "arguments": {
                    "repo": "Prekzursil/AdrianaArt",
                    "tag": "v3.0.0",
                    "notes": "notes",
                    "assets": [str(asset)],
                },
            },
        },
    )
    gate = initial.json()["result"]["structuredContent"]
    assert gate["requires_confirmation"] is True
    token = gate["confirmation_token"]

    confirmed = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "releasebutler.create_release",
                "arguments": {
                    "repo": "Prekzursil/AdrianaArt",
                    "tag": "v3.0.0",
                    "notes": "notes",
                    "assets": [str(asset)],
                    "confirmation_token": token,
                },
            },
        },
    )
    assert confirmed.status_code == 200
    structured = confirmed.json()["result"]["structuredContent"]
    assert structured["uploaded_assets"][0]["name"] == "artifact.zip"
    assert structured["failed_assets"] == []
    assert captured["assets"] == [str(asset)]

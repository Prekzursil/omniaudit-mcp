from __future__ import annotations

import pytest
from omniaudit.core.policy import PolicyEngine, PolicyViolation
from omniaudit.core.rate_limit import InMemoryRateLimiter
from omniaudit.core.settings import settings
from omniaudit.mcp.runtime import (
    AppRuntime,
    MCPRateLimitError,
    MCPToolError,
    _build_github_client,
    _build_object_store,
    build_runtime,
    call_tool,
    list_tools,
)
from omniaudit.modules.auditlens.service import AuditLensService
from omniaudit.modules.releasebutler.service import ReleaseButlerService
from omniaudit.modules.sitelint import service as sitelint_service_module
from omniaudit.modules.sitelint.service import SiteLintService
from omniaudit.security.confirmation import ConfirmationService
from omniaudit.security.risk import RiskGate
from omniaudit.storage.audit_log import AuditLogger
from omniaudit.storage.jobs import JobStore
from omniaudit.storage.receipts import ReceiptStore

from tests.conftest import FakeGitHub


def _make_runtime(
    session_factory, local_store, *, gh=None, repo_allowlist=None, scan_limit=10, write_limit=30
):
    github = gh or FakeGitHub()
    jobs = JobStore(session_factory)
    return AppRuntime(
        policy=PolicyEngine(
            repo_allowlist=repo_allowlist or set(),
            url_allowlist=set(),
            url_denylist=set(),
        ),
        risk_gate=RiskGate(ConfirmationService(secret="secret", ttl_seconds=600)),
        auditlens=AuditLensService(github=github, object_store=local_store),
        sitelint=SiteLintService(
            jobs=jobs, object_store=local_store, reports_root=local_store.root.parent / "reports"
        ),
        releasebutler=ReleaseButlerService(github=github),
        jobs=jobs,
        receipts=ReceiptStore(session_factory, local_store),
        audit_logger=AuditLogger(session_factory),
        scan_rate_limiter=InMemoryRateLimiter(scan_limit),
        github_write_rate_limiter=InMemoryRateLimiter(write_limit),
        object_store_backend="local",
    )


def _confirm(rt, name, args):
    return rt.risk_gate.confirmation_service.issue_token(name, args)


def test_list_tools_has_tools() -> None:
    assert list_tools()["tools"]


def test_sanitize_log_value_strips_newlines_and_truncates() -> None:
    from omniaudit.mcp.runtime import _sanitize_log_value

    assert _sanitize_log_value("a\r\nb") == "a  b"
    assert len(_sanitize_log_value("x" * 500)) == 200


def test_call_tool_unknown_raises_and_logs(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store)
    with pytest.raises(MCPToolError, match="Unknown tool name"):
        call_tool(rt, "nope", {})


def test_auditlens_readonly_tools(session_factory, local_store) -> None:
    gh = FakeGitHub(
        list_workflow_runs=[{"id": 1}],
        list_run_artifacts=[{"id": 2, "name": "ev"}],
        download_artifact_zip=b"z",
        extract_text_files_from_zip={"f": "x"},
    )
    rt = _make_runtime(session_factory, local_store, gh=gh)
    assert call_tool(rt, "auditlens.list_runs", {"repo": "o/r"}) == [{"id": 1}]
    evidence = call_tool(
        rt, "auditlens.fetch_evidence", {"repo": "o/r", "run_id": 2, "artifact_name": "ev"}
    )
    parsed = call_tool(rt, "auditlens.parse_findings", {"evidence_ref": evidence["evidence_ref"]})
    assert "findings_ref" in parsed
    patch = call_tool(rt, "auditlens.propose_patch", {"repo": "o/r", "finding_id": "f1"})
    assert patch["finding_id"] == "f1"


def test_auditlens_create_issue_gate_then_confirm(session_factory, local_store) -> None:
    gh = FakeGitHub(create_issue={"html_url": "u", "number": 5})
    rt = _make_runtime(session_factory, local_store, gh=gh)
    args = {"repo": "o/r", "title": "t", "body": "b", "labels": ["l"]}
    gated = call_tool(rt, "auditlens.create_issue", args)
    assert gated["requires_confirmation"] is True
    token = _confirm(rt, "auditlens.create_issue", args)
    done = call_tool(rt, "auditlens.create_issue", {**args, "confirmation_token": token})
    assert done["issue_number"] == 5
    assert done["receipt_id"].startswith("rcpt_")


def test_create_issue_rate_limited(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store, write_limit=0)
    with pytest.raises(MCPRateLimitError):
        call_tool(
            rt, "auditlens.create_issue", {"repo": "o/r", "title": "t", "body": "b", "labels": []}
        )


def test_create_issue_repo_policy_violation(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store, repo_allowlist={"only/allowed"})
    with pytest.raises(PolicyViolation):
        call_tool(
            rt, "auditlens.create_issue", {"repo": "o/r", "title": "t", "body": "b", "labels": []}
        )


def test_create_issue_without_repo_skips_repo_policy(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store)
    # No repo -> _ensure_repo_policy short-circuits; gate returns confirmation request.
    gated = call_tool(rt, "auditlens.create_issue", {"title": "t", "body": "b", "labels": []})
    assert gated["requires_confirmation"] is True


def test_start_scan_without_url_skips_url_policy(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store)
    # No url -> _ensure_url_policy short-circuits, then the missing arg surfaces as an error.
    with pytest.raises(KeyError):
        call_tool(
            rt, "sitelint.start_scan", {"profile": "standard", "viewport_set": "desktop_mobile"}
        )


def test_sitelint_tools(session_factory, local_store, monkeypatch) -> None:
    monkeypatch.setattr(
        sitelint_service_module,
        "run_sitelint_scan",
        lambda *a, **k: {"findings": [], "metrics": {}, "artifacts": {}, "pages": []},
    )
    rt = _make_runtime(session_factory, local_store)
    started = call_tool(
        rt,
        "sitelint.start_scan",
        {"url": "https://example.com", "profile": "standard", "viewport_set": "desktop_mobile"},
    )
    job_id = started["job_id"]
    assert call_tool(rt, "sitelint.get_scan", {"job_id": job_id})["job_id"] == job_id
    report = call_tool(rt, "sitelint.get_report", {"scan_id": job_id})
    assert report["format"] == "json"


def test_sitelint_start_scan_rate_limited(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store, scan_limit=0)
    with pytest.raises(MCPRateLimitError):
        call_tool(
            rt,
            "sitelint.start_scan",
            {"url": "https://example.com", "profile": "standard", "viewport_set": "desktop_mobile"},
        )


def test_sitelint_export_report_gate_and_confirm(
    session_factory, local_store, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        sitelint_service_module,
        "run_sitelint_scan",
        lambda *a, **k: {"findings": [], "metrics": {}, "artifacts": {}, "pages": []},
    )
    rt = _make_runtime(session_factory, local_store)
    started = call_tool(
        rt,
        "sitelint.start_scan",
        {"url": "https://example.com", "profile": "standard", "viewport_set": "desktop_mobile"},
    )
    dest = str(tmp_path / "out.json")
    args = {"scan_id": started["job_id"], "destination": dest}
    gated = call_tool(rt, "sitelint.export_report", args)
    assert gated["requires_confirmation"] is True
    token = _confirm(rt, "sitelint.export_report", args)
    done = call_tool(rt, "sitelint.export_report", {**args, "confirmation_token": token})
    assert done["receipt_id"].startswith("rcpt_")


def test_export_report_rate_limited(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store, write_limit=0)
    with pytest.raises(MCPRateLimitError):
        call_tool(rt, "sitelint.export_report", {"scan_id": "x", "destination": "d"})


def test_releasebutler_readonly_tools(session_factory, local_store) -> None:
    gh = FakeGitHub(
        get_latest_release={"tag_name": "v1", "assets": []},
        get_release_by_tag={"tag_name": "v1", "assets": []},
        download_release_asset=b"data",
        list_releases=[{"tag_name": "v1"}],
        list_commits=[{"sha": "abc1234", "commit": {"message": "feat: x"}}],
    )
    rt = _make_runtime(session_factory, local_store, gh=gh)
    assert call_tool(rt, "releasebutler.get_latest", {"repo": "o/r"})["tag"] == "v1"
    assert call_tool(rt, "releasebutler.list_assets", {"repo": "o/r", "tag": "v1"})["tag"] == "v1"
    import hashlib

    digest = hashlib.sha256(b"data").hexdigest()
    verified = call_tool(
        rt, "releasebutler.verify_asset", {"repo": "o/r", "asset_id": 1, "checksum_source": digest}
    )
    assert verified["verified"] is True
    notes = call_tool(rt, "releasebutler.generate_notes", {"repo": "o/r"})
    assert "notes" in notes


def test_releasebutler_create_release_gate_and_confirm(session_factory, local_store) -> None:
    gh = FakeGitHub(create_release={"upload_url": "", "html_url": "u", "id": 9})
    rt = _make_runtime(session_factory, local_store, gh=gh)
    args = {"repo": "o/r", "tag": "v1", "notes": "n"}
    gated = call_tool(rt, "releasebutler.create_release", args)
    assert gated["requires_confirmation"] is True
    token = _confirm(rt, "releasebutler.create_release", args)
    done = call_tool(rt, "releasebutler.create_release", {**args, "confirmation_token": token})
    assert done["release_id"] == 9
    assert done["receipt_id"].startswith("rcpt_")


def test_create_release_rate_limited(session_factory, local_store) -> None:
    rt = _make_runtime(session_factory, local_store, write_limit=0)
    with pytest.raises(MCPRateLimitError):
        call_tool(rt, "releasebutler.create_release", {"repo": "o/r", "tag": "v1", "notes": "n"})


def test_core_tools(session_factory, local_store, monkeypatch) -> None:
    monkeypatch.setattr(
        sitelint_service_module,
        "run_sitelint_scan",
        lambda *a, **k: {"findings": [], "metrics": {}, "artifacts": {}, "pages": []},
    )
    rt = _make_runtime(session_factory, local_store)
    started = call_tool(
        rt,
        "sitelint.start_scan",
        {"url": "https://example.com", "profile": "standard", "viewport_set": "desktop_mobile"},
    )
    job = call_tool(rt, "core.get_job", {"job_id": started["job_id"]})
    assert job["status"] == "completed"
    with pytest.raises(MCPToolError, match="Unknown job_id"):
        call_tool(rt, "core.get_job", {"job_id": "missing"})

    # Create a receipt so list_receipts returns rows.
    rt.receipts.create_receipt("op", "actor", {"a": 1}, {"b": 2})
    receipts = call_tool(rt, "core.list_receipts", {})
    assert receipts[0]["operation"] == "op"
    health = call_tool(rt, "core.health", {})
    assert health["status"] == "ok"
    assert "observability" in health


# ---------------- builder helpers ----------------
def test_build_github_client_modes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "github_auth_mode", "app")
    monkeypatch.setattr(settings, "github_app_id", "1")
    monkeypatch.setattr(settings, "github_app_installation_id", "2")
    monkeypatch.setattr(settings, "github_app_private_key", "pem")
    assert _build_github_client().auth_provider.app_id == "1"

    monkeypatch.setattr(settings, "github_app_private_key", None)
    fallback = _build_github_client()
    assert fallback.auth_provider.token == "MISSING_GITHUB_CREDENTIALS"

    monkeypatch.setattr(settings, "github_auth_mode", "pat")
    monkeypatch.setattr(settings, "github_pat", "tok")
    assert _build_github_client().auth_provider.token == "tok"


def test_build_object_store_modes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "object_store_root", tmp_path / "objs")
    monkeypatch.setattr(settings, "object_store_backend", "local")
    assert _build_object_store().__class__.__name__ == "LocalObjectStore"

    monkeypatch.setattr(settings, "object_store_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", None)
    with pytest.raises(MCPToolError, match="OBJECT_STORE_BUCKET"):
        _build_object_store()

    monkeypatch.setattr(settings, "object_store_bucket", "bkt")
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: object())
    store = _build_object_store()
    assert store.__class__.__name__ == "DualReadObjectStore"


def test_build_runtime_local(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "object_store_root", tmp_path / "objs")
    monkeypatch.setattr(settings, "reports_root", tmp_path / "reports")
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(
        settings, "database_url", f"sqlite+pysqlite:///{(tmp_path / 'rt.db').as_posix()}"
    )
    monkeypatch.setattr(settings, "envelope_master_key_file", tmp_path / "secrets" / "master.key")
    monkeypatch.setattr(settings, "sitelint_async_mode", False)
    rt = build_runtime()
    assert rt.object_store_backend == "local"
    assert call_tool(rt, "core.health", {})["status"] == "ok"


def test_build_runtime_async_dispatcher_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "object_store_root", tmp_path / "oa")
    monkeypatch.setattr(settings, "reports_root", tmp_path / "ra")
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(
        settings, "database_url", f"sqlite+pysqlite:///{(tmp_path / 'rt3.db').as_posix()}"
    )
    monkeypatch.setattr(settings, "envelope_master_key_file", tmp_path / "sa" / "master.key")
    monkeypatch.setattr(settings, "sitelint_async_mode", True)
    # worker.tasks is importable (services is on the path) -> dispatcher wired, async mode enabled.
    rt = build_runtime()
    assert rt.sitelint.async_mode is True
    assert rt.sitelint.dispatcher is not None


def test_build_runtime_async_dispatcher_import_failure(monkeypatch, tmp_path) -> None:
    import sys

    monkeypatch.setattr(settings, "object_store_root", tmp_path / "o")
    monkeypatch.setattr(settings, "reports_root", tmp_path / "r")
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(
        settings, "database_url", f"sqlite+pysqlite:///{(tmp_path / 'rt2.db').as_posix()}"
    )
    monkeypatch.setattr(settings, "envelope_master_key_file", tmp_path / "s" / "master.key")
    monkeypatch.setattr(settings, "sitelint_async_mode", True)
    monkeypatch.setitem(sys.modules, "worker.tasks", None)
    rt = build_runtime()
    assert rt.sitelint.async_mode is False

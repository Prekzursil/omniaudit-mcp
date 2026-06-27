from __future__ import annotations

import json
from pathlib import Path

import pytest
from omniaudit.modules.sitelint import service as service_module
from omniaudit.modules.sitelint.service import SiteLintService
from omniaudit.storage.jobs import JobStore


def _report(**extra):
    base = {
        "url": "https://example.com",
        "findings": [{"finding_id": "f1"}],
        "metrics": {"page_count": 2},
        "artifacts": {"screenshots": [], "screenshot_index": []},
        "pages": [],
    }
    base.update(extra)
    return base


@pytest.fixture
def patched_scan(monkeypatch):
    captured = {}

    def fake_scan(url, profile, viewport_set, report_dir, **kwargs):
        captured.update({"url": url, "report_dir": report_dir, **kwargs})
        return _report()

    monkeypatch.setattr(service_module, "run_sitelint_scan", fake_scan)
    return captured


def _service(session_factory, local_store, tmp_path, **kw) -> SiteLintService:
    return SiteLintService(
        jobs=JobStore(session_factory),
        object_store=local_store,
        reports_root=tmp_path / "reports",
        **kw,
    )


def test_start_scan_inline_runs_and_completes(
    session_factory, local_store, tmp_path, patched_scan
) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    out = svc.start_scan(
        url="https://example.com", profile="standard", viewport_set="desktop_mobile"
    )
    assert out["status"] == "completed"
    assert out["finished_at"] is not None


def test_start_scan_idempotent_returns_existing(
    session_factory, local_store, tmp_path, patched_scan
) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    first = svc.start_scan(
        url="https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        idempotency_key="k",
    )
    # Second call with same key finds a non-queued (completed) job and returns its ref.
    second = svc.start_scan(
        url="https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        idempotency_key="k",
    )
    assert first["job_id"] == second["job_id"]


def test_start_scan_async_mode_dispatches(
    session_factory, local_store, tmp_path, patched_scan
) -> None:
    dispatched = {}

    def dispatcher(job_id, payload):
        dispatched["job_id"] = job_id

    svc = _service(session_factory, local_store, tmp_path, async_mode=True, dispatcher=dispatcher)
    out = svc.start_scan(
        url="https://example.com", profile="standard", viewport_set="desktop_mobile"
    )
    assert out["status"] == "queued"
    assert dispatched["job_id"] == out["job_id"]


def test_start_scan_uses_credentials_auth_profile(
    session_factory, local_store, tmp_path, monkeypatch
) -> None:
    seen = {}

    def fake_scan(url, profile, viewport_set, report_dir, **kwargs):
        seen["auth_context"] = kwargs.get("auth_context")
        return _report()

    monkeypatch.setattr(service_module, "run_sitelint_scan", fake_scan)

    class Creds:
        def get_auth_profile(self, name):
            return {"headers": {"X": name}}

    svc = _service(session_factory, local_store, tmp_path, credentials=Creds())
    svc.start_scan(
        url="https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        auth_profile_id="prof",
    )
    assert seen["auth_context"] == {"headers": {"X": "prof"}}


def test_start_scan_with_baseline_diff(session_factory, local_store, tmp_path, monkeypatch) -> None:
    svc = _service(session_factory, local_store, tmp_path)

    # Seed a baseline completed scan.
    baseline_ref = local_store.put_json_immutable(
        {"findings": [{"finding_id": "old"}], "metrics": {"page_count": 1}}
    )
    baseline_job = svc.jobs.create_or_get_job("sitelint", "sitelint.start_scan", "baseline", {})
    svc.jobs.set_job_status(baseline_job.job_id, "completed", 1.0, result_ref=baseline_ref)

    monkeypatch.setattr(service_module, "run_sitelint_scan", lambda *a, **k: _report())
    out = svc.start_scan(
        url="https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        baseline_scan_id=baseline_job.job_id,
    )
    stored = json.loads(local_store.read_text(svc.jobs.get_job(out["job_id"]).result_ref))
    assert stored["baseline_diff"]["fallback_used"] is False
    assert stored["baseline_diff"]["finding_delta"] == 0
    assert stored["baseline_diff"]["page_count_delta"] == 1


def test_baseline_diff_fallback_when_baseline_missing(
    session_factory, local_store, tmp_path, monkeypatch
) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    monkeypatch.setattr(service_module, "run_sitelint_scan", lambda *a, **k: _report())
    out = svc.start_scan(
        url="https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        baseline_scan_id="does-not-exist",
    )
    stored = json.loads(local_store.read_text(svc.jobs.get_job(out["job_id"]).result_ref))
    assert stored["baseline_diff"]["fallback_used"] is True


def test_get_scan_and_missing(session_factory, local_store, tmp_path, patched_scan) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    out = svc.start_scan(
        url="https://example.com", profile="standard", viewport_set="desktop_mobile"
    )
    assert svc.get_scan(out["job_id"])["job_id"] == out["job_id"]
    with pytest.raises(ValueError, match="Unknown job_id"):
        svc.get_scan("missing")


def test_get_report_json_zip_and_errors(
    session_factory, local_store, tmp_path, monkeypatch
) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    screenshot = tmp_path / "shot.png"
    screenshot.write_bytes(b"img")
    report = _report(
        artifacts={"screenshots": [str(screenshot)], "screenshot_index": []},
        pages=[{"url": "u", "screenshot": str(screenshot)}, {"url": "u2", "screenshot": None}],
    )
    monkeypatch.setattr(service_module, "run_sitelint_scan", lambda *a, **k: report)
    out = svc.start_scan(
        url="https://example.com", profile="standard", viewport_set="desktop_mobile"
    )
    scan_id = out["job_id"]

    assert svc.get_report(scan_id, "json")["format"] == "json"
    zipped = svc.get_report(scan_id, "zip")
    assert zipped["format"] == "zip"
    assert zipped["size_bytes"] > 0

    with pytest.raises(ValueError, match="json and zip"):
        svc.get_report(scan_id, "pdf")
    with pytest.raises(ValueError, match="Unknown scan_id"):
        svc.get_report("missing")


def test_get_report_zip_skips_nonlist_and_missing_screenshots(
    session_factory, local_store, tmp_path, monkeypatch
) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    # artifacts.screenshots is not a list, and the page screenshot path does not exist on disk.
    report = _report(
        artifacts={"screenshots": None, "screenshot_index": []},
        pages=[{"url": "u", "screenshot": str(tmp_path / "nope.png")}],
    )
    monkeypatch.setattr(service_module, "run_sitelint_scan", lambda *a, **k: report)
    out = svc.start_scan(
        url="https://example.com", profile="standard", viewport_set="desktop_mobile"
    )
    zipped = svc.get_report(out["job_id"], "zip")
    assert zipped["size_bytes"] > 0


def test_get_report_not_ready(session_factory, local_store, tmp_path) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    job = svc.jobs.create_or_get_job("sitelint", "sitelint.start_scan", "k", {})
    with pytest.raises(ValueError, match="not ready"):
        svc.get_report(job.job_id)


def test_export_report_json_and_zip(session_factory, local_store, tmp_path, monkeypatch) -> None:
    svc = _service(session_factory, local_store, tmp_path)
    monkeypatch.setattr(service_module, "run_sitelint_scan", lambda *a, **k: _report())
    out = svc.start_scan(
        url="https://example.com", profile="standard", viewport_set="desktop_mobile"
    )
    scan_id = out["job_id"]

    json_dest = tmp_path / "out" / "report.json"
    res_json = svc.export_report(scan_id, "json", str(json_dest))
    assert Path(res_json["destination"]).read_text(encoding="utf-8")

    zip_dest = tmp_path / "out" / "report.zip"
    res_zip = svc.export_report(scan_id, "zip", str(zip_dest))
    assert Path(res_zip["destination"]).exists()

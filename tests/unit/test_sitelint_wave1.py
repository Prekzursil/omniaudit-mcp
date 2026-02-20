from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from omniaudit.models.db import Base
from omniaudit.modules.sitelint.service import SiteLintService
from omniaudit.storage.jobs import JobStore
from omniaudit.storage.objects import LocalObjectStore
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _build_service(tmp_path: Path) -> SiteLintService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    jobs = JobStore(session_factory)
    store = LocalObjectStore(tmp_path / "objects")
    return SiteLintService(
        jobs=jobs,
        object_store=store,
        reports_root=tmp_path / "reports",
        async_mode=False,
    )


def test_start_scan_writes_baseline_diff_and_accepts_wave1_args(monkeypatch, tmp_path: Path) -> None:
    service = _build_service(tmp_path)
    call_count = {"n": 0}

    def fake_scan(
        url: str,
        profile: str,
        viewport_set: str,
        report_dir: Path,
        *,
        crawl_budget: int | None = None,
        entry_paths: list[str] | None = None,
        auth_context: dict | None = None,
        max_depth: int | None = None,
        crawl_strategy: str = "bfs",
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        capture_console: bool = False,
        capture_network: bool = False,
        auth_journey_id: str | None = None,
    ) -> dict:
        call_count["n"] += 1
        finding_count = 1 if call_count["n"] == 1 else 3
        return {
            "url": url,
            "profile": profile,
            "viewport_set": viewport_set,
            "crawl_budget": crawl_budget,
            "entry_paths": entry_paths or [],
            "auth_context_used": bool(auth_context),
            "max_depth": max_depth,
            "crawl_strategy": crawl_strategy,
            "include_patterns": include_patterns or [],
            "exclude_patterns": exclude_patterns or [],
            "capture_console": capture_console,
            "capture_network": capture_network,
            "auth_journey_id": auth_journey_id,
            "pages": [{"url": url, "status_code": 200}],
            "findings": [
                {"finding_id": f"finding_{idx}", "severity": "s3", "category": "general", "title": "x"}
                for idx in range(finding_count)
            ],
            "artifacts": {"screenshots": [], "screenshot_index": [], "lighthouse": None, "axe": None},
            "crawl_graph": {"nodes": [{"id": url, "depth": 0}], "edges": []},
        }

    monkeypatch.setattr("omniaudit.modules.sitelint.service.run_sitelint_scan", fake_scan)

    baseline = service.start_scan(
        url="https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
    )
    baseline_job_id = baseline["job_id"]

    second = service.start_scan(
        url="https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        crawl_budget=5,
        entry_paths=["/a", "/b"],
        baseline_scan_id=baseline_job_id,
        max_depth=2,
        crawl_strategy="dfs",
        include_patterns=["/a*"],
        exclude_patterns=["/private*"],
        capture_console=True,
        capture_network=True,
        auth_journey_id="journey-admin",
    )
    report_payload = json.loads(service.get_report(second["job_id"], format_name="json")["report"])

    assert report_payload["crawl_budget"] == 5
    assert report_payload["entry_paths"] == ["/a", "/b"]
    assert report_payload["baseline_diff"]["baseline_scan_id"] == baseline_job_id
    assert report_payload["baseline_diff"]["finding_delta"] == 2
    assert report_payload["baseline_diff"]["fallback_used"] is False
    assert report_payload["baseline_regression_summary"]["new_findings"] == 2
    assert report_payload["crawl_strategy"] == "dfs"
    assert report_payload["auth_journey_id"] == "journey-admin"
    assert report_payload["capture_console"] is True
    assert report_payload["capture_network"] is True
    assert "crawl_graph_ref" in report_payload
    assert "artifact_index_ref" in report_payload


def test_get_report_zip_returns_bundle_ref(monkeypatch, tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    def fake_scan(
        url: str,
        profile: str,
        viewport_set: str,
        report_dir: Path,
        *,
        crawl_budget: int | None = None,
        entry_paths: list[str] | None = None,
        auth_context: dict | None = None,
        max_depth: int | None = None,
        crawl_strategy: str = "bfs",
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        capture_console: bool = False,
        capture_network: bool = False,
        auth_journey_id: str | None = None,
    ) -> dict:
        screenshot_path = report_dir / "page-1.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(b"fake-image")
        return {
            "url": url,
            "profile": profile,
            "viewport_set": viewport_set,
            "pages": [{"url": url, "screenshot": str(screenshot_path), "status_code": 200}],
            "findings": [],
            "artifacts": {
                "screenshots": [str(screenshot_path)],
                "screenshot_index": [{"url": url, "path": str(screenshot_path)}],
                "lighthouse": None,
                "axe": None,
            },
            "crawl_graph": {"nodes": [{"id": url, "depth": 0}], "edges": []},
        }

    monkeypatch.setattr("omniaudit.modules.sitelint.service.run_sitelint_scan", fake_scan)
    job = service.start_scan(url="https://example.com", profile="standard", viewport_set="desktop_mobile")
    zipped = service.get_report(scan_id=job["job_id"], format_name="zip")

    assert zipped["format"] == "zip"
    assert "report_ref" in zipped
    blob = service.object_store.read_bytes(zipped["report_ref"])
    with zipfile.ZipFile(io.BytesIO(blob), mode="r") as archive:
        names = sorted(archive.namelist())
    assert "report.json" in names
    assert any(name.endswith(".png") for name in names)


def test_get_report_sarif_returns_sarif_payload(monkeypatch, tmp_path: Path) -> None:
    service = _build_service(tmp_path)

    def fake_scan(
        url: str,
        profile: str,
        viewport_set: str,
        report_dir: Path,
        **kwargs,
    ) -> dict:
        return {
            "url": url,
            "profile": profile,
            "viewport_set": viewport_set,
            "pages": [{"url": url, "screenshot": None, "status_code": 200}],
            "findings": [
                {
                    "finding_id": "finding_missing_title",
                    "severity": "s2",
                    "category": "seo",
                    "title": "Missing title",
                    "evidence_refs": [{"path_or_url": url, "source_type": "http"}],
                }
            ],
            "artifacts": {"screenshots": [], "screenshot_index": [], "lighthouse": None, "axe": None},
            "crawl_graph": {"nodes": [{"id": url, "depth": 0}], "edges": []},
        }

    monkeypatch.setattr("omniaudit.modules.sitelint.service.run_sitelint_scan", fake_scan)
    job = service.start_scan(url="https://example.com", profile="standard", viewport_set="desktop_mobile")
    sarif = service.get_report(scan_id=job["job_id"], format_name="sarif")
    payload = json.loads(sarif["report"])

    assert sarif["format"] == "sarif"
    assert payload["version"] == "2.1.0"
    assert payload["runs"][0]["results"][0]["ruleId"] == "finding_missing_title"

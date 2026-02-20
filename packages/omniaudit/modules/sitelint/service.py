from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omniaudit.storage.base import ObjectStore
from omniaudit.storage.credentials import SecretCredentialStore
from omniaudit.storage.jobs import JobStore, default_idempotency_key

from .scanner import run_sitelint_scan


@dataclass(slots=True)
class SiteLintService:
    jobs: JobStore
    object_store: ObjectStore
    reports_root: Path
    async_mode: bool = False
    dispatcher: Callable[[str, dict[str, Any]], None] | None = None
    credentials: SecretCredentialStore | None = None

    def start_scan(
        self,
        url: str,
        profile: str,
        viewport_set: str,
        auth_profile: str | None = None,
        idempotency_key: str | None = None,
        crawl_budget: int | None = None,
        entry_paths: list[str] | None = None,
        auth_profile_id: str | None = None,
        baseline_scan_id: str | None = None,
        max_depth: int | None = None,
        crawl_strategy: str | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        capture_console: bool = False,
        capture_network: bool = False,
        auth_journey_id: str | None = None,
    ) -> dict[str, Any]:
        auth_context: dict[str, Any] | None = None
        selected_auth_profile = auth_profile_id or auth_profile
        if selected_auth_profile and self.credentials:
            auth_context = self.credentials.get_auth_profile(selected_auth_profile)

        payload = {
            "url": url,
            "profile": profile,
            "viewport_set": viewport_set,
            "auth_profile": auth_profile,
            "auth_profile_id": auth_profile_id,
            "crawl_budget": crawl_budget,
            "entry_paths": entry_paths or [],
            "baseline_scan_id": baseline_scan_id,
            "max_depth": max_depth,
            "crawl_strategy": crawl_strategy or "bfs",
            "include_patterns": include_patterns or [],
            "exclude_patterns": exclude_patterns or [],
            "capture_console": capture_console,
            "capture_network": capture_network,
            "auth_journey_id": auth_journey_id,
        }
        key = idempotency_key or default_idempotency_key("sitelint.start_scan", payload)
        job = self.jobs.create_or_get_job(
            module="sitelint",
            operation="sitelint.start_scan",
            idempotency_key=key,
            payload=payload,
        )

        if job.status == "queued" and self.async_mode and self.dispatcher:
            self.dispatcher(job.job_id, payload)
            return self._job_ref(job)

        # Local-first default behavior: run scan inline for deterministic single-user deployment.
        if job.status == "queued":
            self.jobs.set_job_status(job.job_id, "running", 0.25)
            report = run_sitelint_scan(
                url,
                profile=profile,
                viewport_set=viewport_set,
                report_dir=self.reports_root / job.job_id,
                crawl_budget=crawl_budget,
                entry_paths=entry_paths,
                auth_context=auth_context,
                max_depth=max_depth,
                crawl_strategy=crawl_strategy or "bfs",
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                capture_console=capture_console,
                capture_network=capture_network,
                auth_journey_id=auth_journey_id,
            )
            crawl_graph_ref = self.object_store.put_json_immutable(report.get("crawl_graph", {}))
            artifact_index_doc = {
                "screenshots": report.get("artifacts", {}).get("screenshot_index", []),
                "pages": [page.get("url") for page in report.get("pages", [])],
            }
            artifact_index_ref = self.object_store.put_json_immutable(artifact_index_doc)
            report["crawl_graph_ref"] = crawl_graph_ref
            report["artifact_index_ref"] = artifact_index_ref
            if baseline_scan_id:
                report["baseline_diff"] = self._baseline_diff(current_report=report, baseline_scan_id=baseline_scan_id)
                report["baseline_regression_summary"] = self._baseline_regression_summary(
                    current_report=report,
                    baseline_scan_id=baseline_scan_id,
                )
            else:
                report["baseline_regression_summary"] = None
            result_ref = self.object_store.put_json_immutable(report)
            job = self.jobs.set_job_status(job.job_id, "completed", 1.0, result_ref=result_ref) or job

        return self._job_ref(job)

    def get_scan(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get_job(job_id)
        if not job:
            raise ValueError(f"Unknown job_id: {job_id}")
        return self._job_ref(job)

    def get_report(self, scan_id: str, format_name: str = "json") -> dict[str, Any]:
        job = self.jobs.get_job(scan_id)
        if not job:
            raise ValueError(f"Unknown scan_id: {scan_id}")
        if not job.result_ref:
            raise ValueError("Scan report is not ready")

        report_text = self.object_store.read_text(job.result_ref)

        if format_name == "zip":
            bundle = self._build_report_zip(report_text)
            bundle_ref = self.object_store.put_bytes_immutable(bundle, suffix=".zip")
            return {
                "scan_id": scan_id,
                "format": "zip",
                "report_ref": bundle_ref,
                "size_bytes": len(bundle),
            }
        if format_name == "sarif":
            sarif_text = self._build_sarif_report(scan_id=scan_id, report_text=report_text)
            return {
                "scan_id": scan_id,
                "format": "sarif",
                "report": sarif_text,
            }
        if format_name != "json":
            raise ValueError("Only json, zip, and sarif formats are currently supported")

        return {
            "scan_id": scan_id,
            "format": format_name,
            "report": report_text,
        }

    def export_report(self, scan_id: str, format_name: str, destination: str) -> dict[str, Any]:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if format_name == "zip":
            report = self.get_report(scan_id, format_name="zip")
            target.write_bytes(self.object_store.read_bytes(report["report_ref"]))
        elif format_name == "sarif":
            report = self.get_report(scan_id, format_name="sarif")
            target.write_text(report["report"], encoding="utf-8")
        else:
            report = self.get_report(scan_id, format_name="json")
            target.write_text(report["report"], encoding="utf-8")
        return {
            "scan_id": scan_id,
            "destination": str(target),
            "format": format_name,
        }

    @staticmethod
    def _job_ref(job) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "module": job.module,
            "status": job.status,
            "progress": job.progress,
            "started_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.updated_at.isoformat() if job.status == "completed" else None,
        }

    def _baseline_diff(self, current_report: dict[str, Any], baseline_scan_id: str) -> dict[str, Any]:
        baseline_job = self.jobs.get_job(baseline_scan_id)
        if not baseline_job or not baseline_job.result_ref:
            return {
                "baseline_scan_id": baseline_scan_id,
                "fallback_used": True,
                "error": "baseline_scan_id not found",
            }
        baseline_report = json.loads(self.object_store.read_text(baseline_job.result_ref))
        current_findings = len(current_report.get("findings", []))
        baseline_findings = len(baseline_report.get("findings", []))
        current_pages = int(current_report.get("metrics", {}).get("page_count", 0))
        baseline_pages = int(baseline_report.get("metrics", {}).get("page_count", 0))
        return {
            "baseline_scan_id": baseline_scan_id,
            "fallback_used": False,
            "finding_delta": current_findings - baseline_findings,
            "page_count_delta": current_pages - baseline_pages,
        }

    def _baseline_regression_summary(self, current_report: dict[str, Any], baseline_scan_id: str) -> dict[str, Any]:
        baseline_job = self.jobs.get_job(baseline_scan_id)
        if not baseline_job or not baseline_job.result_ref:
            return {
                "baseline_scan_id": baseline_scan_id,
                "fallback_used": True,
                "new_findings": 0,
                "resolved_findings": 0,
                "unchanged_findings": 0,
            }

        baseline_report = json.loads(self.object_store.read_text(baseline_job.result_ref))
        current_ids = {str(item.get("finding_id")) for item in current_report.get("findings", []) if item.get("finding_id")}
        baseline_ids = {str(item.get("finding_id")) for item in baseline_report.get("findings", []) if item.get("finding_id")}

        new_ids = sorted(current_ids - baseline_ids)
        resolved_ids = sorted(baseline_ids - current_ids)
        unchanged_ids = sorted(current_ids & baseline_ids)
        return {
            "baseline_scan_id": baseline_scan_id,
            "fallback_used": False,
            "new_findings": len(new_ids),
            "resolved_findings": len(resolved_ids),
            "unchanged_findings": len(unchanged_ids),
            "new_finding_ids": new_ids,
            "resolved_finding_ids": resolved_ids,
        }

    @staticmethod
    def _build_report_zip(report_text: str) -> bytes:
        payload = json.loads(report_text)
        screenshot_paths = []
        artifacts = payload.get("artifacts", {})
        if isinstance(artifacts.get("screenshots"), list):
            screenshot_paths.extend(str(item) for item in artifacts["screenshots"])
        pages = payload.get("pages", [])
        for page in pages:
            path = page.get("screenshot")
            if path:
                screenshot_paths.append(str(path))

        unique_screenshots = []
        seen = set()
        for path in screenshot_paths:
            if path in seen:
                continue
            seen.add(path)
            unique_screenshots.append(path)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.json", report_text)
            for path in unique_screenshots:
                file_path = Path(path)
                if file_path.exists() and file_path.is_file():
                    archive.write(file_path, arcname=f"screenshots/{file_path.name}")
        return buffer.getvalue()

    @staticmethod
    def _build_sarif_report(scan_id: str, report_text: str) -> str:
        payload = json.loads(report_text)
        severity_level = {"s1": "error", "s2": "warning", "s3": "note"}
        findings = payload.get("findings", [])
        results: list[dict[str, Any]] = []
        for finding in findings:
            finding_id = str(finding.get("finding_id", "unknown"))
            title = str(finding.get("title", "Unspecified finding"))
            severity = str(finding.get("severity", "s3")).lower()
            evidence = finding.get("evidence_refs", [])
            first_evidence = evidence[0] if evidence else {}
            location_uri = str(first_evidence.get("path_or_url", payload.get("url", "")))
            results.append(
                {
                    "ruleId": finding_id,
                    "level": severity_level.get(severity, "note"),
                    "message": {"text": title},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": location_uri},
                            }
                        }
                    ],
                }
            )

        sarif = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "OmniAudit SiteLint", "version": "wave2"}},
                    "automationDetails": {"id": scan_id},
                    "results": results,
                }
            ],
        }
        return json.dumps(sarif, indent=2)

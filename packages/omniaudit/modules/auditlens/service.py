from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from omniaudit.modules.auditlens.parser import parse_deterministic_findings
from omniaudit.modules.github.client import GitHubClient
from omniaudit.storage.base import ObjectStore


@dataclass(slots=True)
class AuditLensService:
    github: GitHubClient
    object_store: ObjectStore

    def list_runs(self, repo: str, pr_number: int | None = None, branch: str | None = None) -> list[dict[str, Any]]:
        runs = self.github.list_workflow_runs(repo, branch=branch)
        if pr_number is None:
            return runs

        filtered: list[dict[str, Any]] = []
        for run in runs:
            pull_requests = run.get("pull_requests", [])
            if any(pr.get("number") == pr_number for pr in pull_requests):
                filtered.append(run)
        return filtered

    def fetch_evidence(self, repo: str, run_id: int, artifact_name: str) -> dict[str, Any]:
        artifacts = self.github.list_run_artifacts(repo, run_id)
        selected = next((item for item in artifacts if item.get("name") == artifact_name), None)
        if not selected:
            raise ValueError(f"Artifact '{artifact_name}' not found for run {run_id}")

        zip_bytes = self.github.download_artifact_zip(repo, selected["id"])
        files = self.github.extract_text_files_from_zip(zip_bytes)
        evidence_doc = {
            "repo": repo,
            "run_id": run_id,
            "artifact_name": artifact_name,
            "artifact_id": selected["id"],
            "files": files,
        }
        evidence_ref = self.object_store.put_json_immutable(evidence_doc)
        return {
            "evidence_ref": evidence_ref,
            "artifact_id": selected["id"],
            "file_count": len(files),
        }

    def parse_findings(
        self,
        evidence_ref: str,
        ruleset_version: str = "v1",
        parser_profile: str = "auto",
        dedupe_strategy: str = "by_id",
        parser_profile_version: str | None = None,
        confidence_profile: str | None = None,
        merge_window: int | None = None,
        ownership_map_ref: str | None = None,
    ) -> dict[str, Any]:
        document = json.loads(self.object_store.read_text(evidence_ref))
        files: dict[str, str] = document.get("files", {})

        findings = self._findings_from_files(files, parser_profile=parser_profile)
        findings = self._dedupe_findings(findings, dedupe_strategy=dedupe_strategy)
        findings = self._merge_findings_window(findings, merge_window=merge_window)
        calibration_profile = confidence_profile or "severity-bump-v1"
        findings = [self._calibrate_confidence(item, profile=calibration_profile) for item in findings]
        clusters = self._cluster_findings(findings)
        owner_suggestions = self._owner_suggestions(findings, ownership_map_ref=ownership_map_ref)

        findings_doc = {
            "ruleset_version": ruleset_version,
            "parser_profile": parser_profile,
            "parser_profile_version": parser_profile_version,
            "dedupe_strategy": dedupe_strategy,
            "merge_window": merge_window,
            "confidence_profile": calibration_profile,
            "ownership_map_ref": ownership_map_ref,
            "findings": findings,
            "clusters": clusters,
            "owner_suggestions": owner_suggestions,
            "source_evidence_ref": evidence_ref,
        }
        findings_ref = self.object_store.put_json_immutable(findings_doc)
        return {
            "findings_ref": findings_ref,
            "findings": findings,
            "clusters": clusters,
            "owner_suggestions": owner_suggestions,
            "calibration_profile_used": calibration_profile,
            "count": len(findings),
        }

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: list[str],
        finding_ids: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
        template_id: str | None = None,
        project_id: str | None = None,
        issue_type: str | None = None,
        dedupe_key: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        final_body = body
        if template_id:
            final_body = f"Template: {template_id}\n\n{final_body}"
        if finding_ids:
            final_body += "\n\nLinked findings:\n" + "\n".join(f"- {fid}" for fid in finding_ids)
        metadata: list[str] = []
        if project_id:
            metadata.append(f"project_id={project_id}")
        if issue_type:
            metadata.append(f"issue_type={issue_type}")
        if dedupe_key:
            metadata.append(f"dedupe_key={dedupe_key}")
        if metadata:
            final_body += "\n\nMetadata:\n" + "\n".join(f"- {item}" for item in metadata)

        if dry_run:
            return {
                "repo": repo,
                "issue_url": None,
                "issue_number": None,
                "dry_run": True,
                "title": title,
                "labels": labels,
                "assignees": assignees or [],
                "milestone": milestone,
                "project_id": project_id,
                "issue_type": issue_type,
                "dedupe_key": dedupe_key,
            }

        issue = self.github.create_issue(
            repo=repo,
            title=title,
            body=final_body,
            labels=labels,
            assignees=assignees,
            milestone=milestone,
        )
        return {
            "issue_url": issue.get("html_url"),
            "issue_number": issue.get("number"),
            "repo": repo,
            "dry_run": False,
            "project_id": project_id,
            "issue_type": issue_type,
            "dedupe_key": dedupe_key,
        }

    @staticmethod
    def propose_patch(repo: str, finding_id: str) -> dict[str, Any]:
        digest = hashlib.sha256(finding_id.encode("utf-8")).hexdigest()[:8]
        target_file = f"src/audit/findings/{digest}.md"
        diff = (
            f"diff --git a/{target_file} b/{target_file}\n"
            f"--- a/{target_file}\n"
            f"+++ b/{target_file}\n"
            "@@ -1,1 +1,1 @@\n"
            f"-TODO unresolved finding {finding_id}\n"
            f"+Resolved finding {finding_id} with deterministic patch guidance.\n"
        )
        return {
            "repo": repo,
            "finding_id": finding_id,
            "target_file": target_file,
            "diff_preview": diff,
        }

    @staticmethod
    def _fallback_findings_from_files(files: dict[str, str]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for path, content in files.items():
            if "console-errors" in path and "Unexpected token" in content:
                findings.append(
                    {
                        "finding_id": "finding_console_unexpected_token",
                        "severity": "s3",
                        "category": "correctness",
                        "title": "Unexpected token errors in console",
                        "confidence": 0.9,
                        "suggested_fix": "Investigate client bundle mismatch or invalid HTML response",
                        "evidence_refs": [{"source_type": "artifact", "path_or_url": path}],
                    }
                )
        return findings

    @staticmethod
    def _lighthouse_findings_from_files(files: dict[str, str]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for path, content in files.items():
            if "lighthouse" not in path.lower():
                continue
            try:
                payload = json.loads(content)
                seo_score = float(payload.get("categories", {}).get("seo", {}).get("score", 1.0))
            except Exception:
                continue
            if seo_score < 0.8:
                findings.append(
                    {
                        "finding_id": "finding_lighthouse_seo_low",
                        "severity": "s3",
                        "category": "seo",
                        "title": "Lighthouse SEO score below threshold",
                        "confidence": 0.8,
                        "suggested_fix": "Review Lighthouse diagnostics for metadata and semantic markup.",
                        "evidence_refs": [{"source_type": "artifact", "path_or_url": path}],
                    }
                )
        return findings

    @classmethod
    def _findings_from_files(cls, files: dict[str, str], parser_profile: str) -> list[dict[str, Any]]:
        profile = parser_profile.strip().lower()
        deterministic_payload = next(
            (content for name, content in files.items() if name.endswith("deterministic-findings.json")),
            None,
        )

        if profile == "deterministic":
            return parse_deterministic_findings(deterministic_payload or '{"findings":[]}')
        if profile == "console":
            return cls._fallback_findings_from_files(files)
        if profile == "lighthouse":
            return cls._lighthouse_findings_from_files(files)

        findings: list[dict[str, Any]] = []
        if deterministic_payload:
            findings.extend(parse_deterministic_findings(deterministic_payload))
        findings.extend(cls._fallback_findings_from_files(files))
        findings.extend(cls._lighthouse_findings_from_files(files))
        return findings

    @staticmethod
    def _dedupe_findings(findings: list[dict[str, Any]], dedupe_strategy: str) -> list[dict[str, Any]]:
        strategy = dedupe_strategy.strip().lower()
        output: list[dict[str, Any]] = []
        seen: set[str] = set()
        for finding in findings:
            if strategy == "by_title":
                key = f"{finding.get('category','general')}::{finding.get('title','')}"
            else:
                key = str(finding.get("finding_id", ""))
            if key in seen:
                continue
            seen.add(key)
            output.append(finding)
        return output

    @staticmethod
    def _calibrate_confidence(finding: dict[str, Any], profile: str = "severity-bump-v1") -> dict[str, Any]:
        calibrated = dict(finding)
        current = float(calibrated.get("confidence", 0.8))
        severity = str(calibrated.get("severity", "s3")).lower()
        selected = (profile or "severity-bump-v1").strip().lower()
        bump_table = {
            "severity-bump-v1": {"s1": 0.12, "s2": 0.08, "s3": 0.04},
            "strict": {"s1": 0.08, "s2": 0.05, "s3": 0.02},
            "aggressive": {"s1": 0.18, "s2": 0.12, "s3": 0.06},
        }
        bump = bump_table.get(selected, bump_table["severity-bump-v1"]).get(severity, 0.02)
        calibrated["confidence"] = min(1.0, round(current + bump, 4))
        return calibrated

    @staticmethod
    def _merge_findings_window(findings: list[dict[str, Any]], merge_window: int | None = None) -> list[dict[str, Any]]:
        if merge_window is None or merge_window <= 1:
            return findings
        merged: list[dict[str, Any]] = []
        last_seen: dict[str, int] = {}
        for idx, finding in enumerate(findings):
            key = f"{finding.get('category', 'general')}::{finding.get('title', '')}"
            previous = last_seen.get(key)
            if previous is not None and idx - previous <= merge_window:
                continue
            last_seen[key] = idx
            merged.append(finding)
        return merged

    @staticmethod
    def _cluster_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[str]] = {}
        for finding in findings:
            category = str(finding.get("category", "general"))
            severity = str(finding.get("severity", "s3"))
            key = (category, severity)
            grouped.setdefault(key, []).append(str(finding.get("finding_id", "unknown")))
        clusters = [
            {"cluster_id": f"{category}:{severity}", "category": category, "severity": severity, "finding_ids": ids}
            for (category, severity), ids in grouped.items()
        ]
        return sorted(clusters, key=lambda item: item["cluster_id"])

    def _owner_suggestions(self, findings: list[dict[str, Any]], ownership_map_ref: str | None = None) -> list[dict[str, Any]]:
        ownership_rules: list[dict[str, str]] = []
        if ownership_map_ref:
            try:
                ownership_doc = json.loads(self.object_store.read_text(ownership_map_ref))
                raw_rules = ownership_doc.get("rules", [])
                if isinstance(raw_rules, list):
                    for entry in raw_rules:
                        if isinstance(entry, dict):
                            pattern = str(entry.get("pattern", "")).strip()
                            owner = str(entry.get("owner", "")).strip()
                            if pattern and owner:
                                ownership_rules.append({"pattern": pattern, "owner": owner})
            except Exception:
                ownership_rules = []

        owner_counts: dict[str, int] = {}
        for finding in findings:
            candidate_owner = "unowned"
            evidence_refs = finding.get("evidence_refs", [])
            for evidence in evidence_refs:
                path = str(evidence.get("path_or_url", ""))
                for rule in ownership_rules:
                    if rule["pattern"] in path:
                        candidate_owner = rule["owner"]
                        break
                if candidate_owner != "unowned":
                    break
            owner_counts[candidate_owner] = owner_counts.get(candidate_owner, 0) + 1

        ranked = sorted(owner_counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"owner": owner, "finding_count": count} for owner, count in ranked]

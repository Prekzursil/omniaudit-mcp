from __future__ import annotations

import json
from pathlib import Path

from omniaudit.modules.auditlens.service import AuditLensService
from omniaudit.storage.objects import LocalObjectStore


class FakeGitHubAudit:
    def __init__(self) -> None:
        self.issue_payload: dict | None = None

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
    ) -> dict:
        self.issue_payload = {
            "repo": repo,
            "title": title,
            "body": body,
            "labels": labels or [],
            "assignees": assignees or [],
            "milestone": milestone,
        }
        return {"html_url": f"https://github.com/{repo}/issues/99", "number": 99}


def test_parse_findings_supports_parser_profile_and_dedupe(tmp_path: Path) -> None:
    github = FakeGitHubAudit()
    store = LocalObjectStore(tmp_path / "objects")
    service = AuditLensService(github=github, object_store=store)

    evidence_doc = {
        "repo": "o/r",
        "run_id": 1,
        "artifact_name": "evidence",
        "artifact_id": 2,
        "files": {
            "console-errors.log": "Unexpected token at line 1\nUnexpected token at line 2",
            "metrics/lighthouse.json": json.dumps({"categories": {"seo": {"score": 0.42}}}),
        },
    }
    evidence_ref = store.put_json_immutable(evidence_doc)
    parsed = service.parse_findings(
        evidence_ref=evidence_ref,
        ruleset_version="v2",
        parser_profile="auto",
        dedupe_strategy="by_title",
        parser_profile_version="2026.02",
        confidence_profile="strict",
        merge_window=2,
    )

    assert parsed["count"] >= 1
    assert all("confidence" in finding for finding in parsed["findings"])
    titles = [finding["title"] for finding in parsed["findings"]]
    assert len(titles) == len(set(titles))
    assert parsed["calibration_profile_used"] == "strict"
    assert isinstance(parsed["clusters"], list)
    assert isinstance(parsed["owner_suggestions"], list)


def test_create_issue_supports_assignees_milestone_and_template(tmp_path: Path) -> None:
    github = FakeGitHubAudit()
    store = LocalObjectStore(tmp_path / "objects")
    service = AuditLensService(github=github, object_store=store)

    result = service.create_issue(
        repo="Prekzursil/omniaudit-mcp",
        title="Audit finding",
        body="Base body",
        labels=["audit:ux"],
        finding_ids=["finding_1"],
        assignees=["Prekzursil"],
        milestone=1,
        template_id="audit_default",
    )

    assert result["issue_number"] == 99
    assert github.issue_payload is not None
    assert github.issue_payload["assignees"] == ["Prekzursil"]
    assert github.issue_payload["milestone"] == 1
    assert "Linked findings" in github.issue_payload["body"]
    assert "Template: audit_default" in github.issue_payload["body"]


def test_propose_patch_returns_file_anchored_diff() -> None:
    result = AuditLensService.propose_patch(repo="o/r", finding_id="finding_abcd1234")
    assert "diff --git" in result["diff_preview"]
    assert "target_file" in result
    assert result["target_file"].startswith("src/")


def test_create_issue_supports_wave2_dry_run_metadata(tmp_path: Path) -> None:
    github = FakeGitHubAudit()
    store = LocalObjectStore(tmp_path / "objects")
    service = AuditLensService(github=github, object_store=store)

    result = service.create_issue(
        repo="Prekzursil/omniaudit-mcp",
        title="Audit finding",
        body="Base body",
        labels=["audit:ux"],
        project_id="ops-board",
        issue_type="task",
        dedupe_key="audit-123",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["issue_number"] is None
    assert result["project_id"] == "ops-board"
    assert github.issue_payload is None

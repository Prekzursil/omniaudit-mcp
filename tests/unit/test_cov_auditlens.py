from __future__ import annotations

import io
import json
import zipfile

import pytest
from omniaudit.modules.auditlens.service import AuditLensService

from tests.conftest import FakeGitHub


def _service(local_store, **gh):
    return AuditLensService(github=FakeGitHub(**gh), object_store=local_store)


def test_list_runs_all_and_filtered(local_store) -> None:
    runs = [
        {"id": 1, "pull_requests": [{"number": 5}]},
        {"id": 2, "pull_requests": [{"number": 9}]},
    ]
    svc = _service(local_store, list_workflow_runs=runs)
    assert svc.list_runs("o/r") == runs
    assert svc.list_runs("o/r", pr_number=5) == [runs[0]]
    assert svc.list_runs("o/r", pr_number=404) == []


def test_fetch_evidence_success_and_missing(local_store) -> None:
    svc = _service(
        local_store,
        list_run_artifacts=[{"id": 11, "name": "evidence"}],
        download_artifact_zip=b"zip",
        extract_text_files_from_zip={"a.txt": "hi"},
    )
    result = svc.fetch_evidence("o/r", 1, "evidence")
    assert result["artifact_id"] == 11
    assert result["file_count"] == 1
    assert json.loads(local_store.read_text(result["evidence_ref"]))["files"] == {"a.txt": "hi"}

    missing = _service(local_store, list_run_artifacts=[{"id": 1, "name": "other"}])
    with pytest.raises(ValueError, match="not found"):
        missing.fetch_evidence("o/r", 1, "evidence")


def _evidence_ref(local_store, files: dict[str, str]) -> str:
    return local_store.put_json_immutable({"files": files})


def test_parse_findings_deterministic_profile(local_store) -> None:
    payload = json.dumps({"findings": [{"finding_id": "f1", "severity": "s1", "title": "x"}]})
    ref = _evidence_ref(local_store, {"deterministic-findings.json": payload})
    svc = _service(local_store)
    out = svc.parse_findings(ref, parser_profile="deterministic")
    assert out["count"] == 1
    assert out["findings"][0]["confidence"] == pytest.approx(0.92)  # s1 bump on default 0.8


def test_parse_findings_console_profile(local_store) -> None:
    ref = _evidence_ref(local_store, {"console-errors.log": "Unexpected token <"})
    out = _service(local_store).parse_findings(ref, parser_profile="console")
    assert out["findings"][0]["finding_id"] == "finding_console_unexpected_token"


def test_parse_findings_lighthouse_profile_and_branches(local_store) -> None:
    files = {
        "lighthouse.json": json.dumps({"categories": {"seo": {"score": 0.5}}}),
        "lighthouse-good.json": json.dumps({"categories": {"seo": {"score": 0.95}}}),
        "lighthouse-bad.json": "not-json",
        "other.txt": "ignored",
    }
    ref = _evidence_ref(local_store, files)
    out = _service(local_store).parse_findings(ref, parser_profile="lighthouse")
    ids = {f["finding_id"] for f in out["findings"]}
    assert ids == {"finding_lighthouse_seo_low"}


def test_parse_findings_auto_combines_and_dedupes(local_store) -> None:
    det = json.dumps(
        {"findings": [{"finding_id": "dup", "severity": "s2", "title": "T", "category": "seo"}]}
    )
    files = {
        "deterministic-findings.json": det,
        "console-errors.log": "Unexpected token",
        "lighthouse.json": json.dumps({"categories": {"seo": {"score": 0.1}}}),
    }
    ref = _evidence_ref(local_store, files)
    svc = _service(local_store)
    by_id = svc.parse_findings(ref, dedupe_strategy="by_id")
    assert by_id["count"] == 3
    by_title = svc.parse_findings(ref, dedupe_strategy="by_title")
    assert by_title["count"] == 3


def test_parse_findings_auto_without_deterministic_payload(local_store) -> None:
    # No deterministic-findings.json -> the deterministic branch is skipped.
    ref = _evidence_ref(local_store, {"console-errors.log": "Unexpected token"})
    out = _service(local_store).parse_findings(ref, parser_profile="auto")
    assert out["findings"][0]["finding_id"] == "finding_console_unexpected_token"


def test_dedupe_by_title_collapses_duplicates(local_store) -> None:
    det = json.dumps(
        {
            "findings": [
                {"finding_id": "a", "severity": "s3", "title": "Same", "category": "seo"},
                {"finding_id": "b", "severity": "s3", "title": "Same", "category": "seo"},
            ]
        }
    )
    ref = _evidence_ref(local_store, {"deterministic-findings.json": det})
    out = _service(local_store).parse_findings(
        ref, parser_profile="deterministic", dedupe_strategy="by_title"
    )
    assert out["count"] == 1


def test_calibrate_confidence_unknown_severity(local_store) -> None:
    det = json.dumps({"findings": [{"finding_id": "x", "severity": "s9", "title": "t"}]})
    ref = _evidence_ref(local_store, {"deterministic-findings.json": det})
    out = _service(local_store).parse_findings(ref, parser_profile="deterministic")
    assert out["findings"][0]["confidence"] == pytest.approx(0.82)  # default bump 0.02


def test_create_issue_with_template_and_findings(local_store) -> None:
    svc = _service(local_store, create_issue={"html_url": "u", "number": 7})
    out = svc.create_issue(
        "o/r", "title", "body", labels=["l"], finding_ids=["f1", "f2"], template_id="tmpl"
    )
    assert out["issue_number"] == 7
    sent_body = svc.github.calls[0][1][2]
    assert sent_body.startswith("Template: tmpl")
    assert "Linked findings" in sent_body


def test_create_issue_minimal(local_store) -> None:
    svc = _service(local_store, create_issue={"html_url": "u", "number": 1})
    out = svc.create_issue("o/r", "t", "b", labels=[])
    assert out["repo"] == "o/r"


def test_propose_patch(local_store) -> None:
    out = _service(local_store).propose_patch("o/r", "finding-123")
    assert out["finding_id"] == "finding-123"
    assert out["target_file"].startswith("src/audit/findings/")
    assert "diff --git" in out["diff_preview"]


def test_extract_zip_roundtrip_helper() -> None:
    # Sanity helper to keep zip semantics aligned with evidence extraction.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.txt", "y")
    assert buffer.getvalue()[:2] == b"PK"

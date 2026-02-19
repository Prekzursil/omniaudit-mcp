from __future__ import annotations

import hashlib
import json
from typing import Any


def parse_deterministic_findings(raw_json: str) -> list[dict[str, Any]]:
    payload = json.loads(raw_json)
    source_findings: list[dict[str, Any]] = payload.get("findings", [])
    normalized: list[dict[str, Any]] = []

    for finding in source_findings:
        normalized_finding = {
            "finding_id": _make_finding_id(finding),
            "severity": finding.get("severity", "s3"),
            "category": finding.get("category", "general"),
            "title": finding.get("title", "Untitled finding"),
            "evidence_refs": finding.get("evidence", []),
            "confidence": float(finding.get("confidence", 0.8)),
            "suggested_fix": finding.get("suggested_fix", "Investigate and patch"),
        }
        normalized.append(normalized_finding)

    return normalized


def _make_finding_id(finding: dict[str, Any]) -> str:
    fingerprint_input = json.dumps(
        {
            "severity": finding.get("severity"),
            "category": finding.get("category"),
            "title": finding.get("title"),
            "evidence": finding.get("evidence", []),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()[:16]
    return f"finding_{digest}"

from pathlib import Path

from omniaudit.modules.auditlens.parser import parse_deterministic_findings


def test_parse_deterministic_findings_normalizes_shape() -> None:
    fixture_path = Path("tests/fixtures/adriana_deterministic_findings.json")
    findings = parse_deterministic_findings(fixture_path.read_text(encoding="utf-8"))

    assert len(findings) == 2
    assert findings[0]["severity"] == "s2"
    assert findings[0]["finding_id"].startswith("finding_")

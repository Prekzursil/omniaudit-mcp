from omniaudit.mcp.registry import TOOL_NAMES


def test_tool_registry_contains_required_tool_names() -> None:
    required = {
        "auditlens.list_runs",
        "auditlens.fetch_evidence",
        "auditlens.parse_findings",
        "auditlens.create_issue",
        "auditlens.propose_patch",
        "sitelint.start_scan",
        "sitelint.get_scan",
        "sitelint.get_report",
        "sitelint.export_report",
        "releasebutler.get_latest",
        "releasebutler.list_assets",
        "releasebutler.verify_asset",
        "releasebutler.generate_notes",
        "releasebutler.create_release",
        "core.get_job",
        "core.list_receipts",
        "core.health",
    }

    assert required.issubset(set(TOOL_NAMES))

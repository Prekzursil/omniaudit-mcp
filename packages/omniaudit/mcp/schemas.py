from __future__ import annotations

TOOLS = [
    {
        "name": "auditlens.list_runs",
        "description": "List GitHub workflow runs for a repository and optional PR/branch.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {
                "repo": {"type": "string"},
                "pr_number": {"type": "integer"},
                "branch": {"type": "string"},
            },
        },
    },
    {
        "name": "auditlens.fetch_evidence",
        "description": "Fetch and store evidence artifact from a workflow run.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo", "run_id", "artifact_name"],
            "properties": {
                "repo": {"type": "string"},
                "run_id": {"type": "integer"},
                "artifact_name": {"type": "string"},
            },
        },
    },
    {
        "name": "auditlens.parse_findings",
        "description": "Parse normalized findings from stored evidence reference.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["evidence_ref"],
            "properties": {
                "evidence_ref": {"type": "string"},
                "ruleset_version": {"type": "string"},
                "parser_profile": {"type": "string"},
                "dedupe_strategy": {"type": "string"},
            },
        },
    },
    {
        "name": "auditlens.create_issue",
        "description": "Create a GitHub issue from findings.",
        "annotations": {"openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo", "title", "body", "labels"],
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "finding_ids": {"type": "array", "items": {"type": "string"}},
                "assignees": {"type": "array", "items": {"type": "string"}},
                "milestone": {"type": "integer"},
                "template_id": {"type": "string"},
                "confirmation_token": {"type": "string"},
            },
        },
    },
    {
        "name": "auditlens.propose_patch",
        "description": "Generate a read-only patch preview for a finding.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo", "finding_id"],
            "properties": {
                "repo": {"type": "string"},
                "finding_id": {"type": "string"},
            },
        },
    },
    {
        "name": "sitelint.start_scan",
        "description": "Start a site scan and return a job reference.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["url", "profile", "viewport_set"],
            "properties": {
                "url": {"type": "string"},
                "profile": {"type": "string"},
                "viewport_set": {"type": "string"},
                "auth_profile": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "crawl_budget": {"type": "integer"},
                "entry_paths": {"type": "array", "items": {"type": "string"}},
                "auth_profile_id": {"type": "string"},
                "baseline_scan_id": {"type": "string"},
            },
        },
    },
    {
        "name": "sitelint.get_scan",
        "description": "Get job status for a site scan.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {"job_id": {"type": "string"}},
        },
    },
    {
        "name": "sitelint.get_report",
        "description": "Return scan report data.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["scan_id"],
            "properties": {
                "scan_id": {"type": "string"},
                "format": {"type": "string"},
            },
        },
    },
    {
        "name": "sitelint.export_report",
        "description": "Export scan report to a destination file.",
        "annotations": {"openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["scan_id", "format", "destination"],
            "properties": {
                "scan_id": {"type": "string"},
                "format": {"type": "string"},
                "destination": {"type": "string"},
                "confirmation_token": {"type": "string"},
            },
        },
    },
    {
        "name": "releasebutler.get_latest",
        "description": "Get latest release metadata.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {"repo": {"type": "string"}},
        },
    },
    {
        "name": "releasebutler.list_assets",
        "description": "List assets for a release tag or latest release.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {
                "repo": {"type": "string"},
                "tag": {"type": "string"},
            },
        },
    },
    {
        "name": "releasebutler.verify_asset",
        "description": "Verify release asset checksum.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo", "asset_id", "checksum_source"],
            "properties": {
                "repo": {"type": "string"},
                "asset_id": {"type": "integer"},
                "checksum_source": {"type": "string"},
            },
        },
    },
    {
        "name": "releasebutler.generate_notes",
        "description": "Generate release notes from tag-to-tag compare with deterministic fallback.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo"],
            "properties": {
                "repo": {"type": "string"},
                "tag": {"type": "string"},
                "window": {"type": "integer"},
                "from_tag": {"type": "string"},
                "to_tag": {"type": "string"},
                "fallback_window": {"type": "integer"},
                "group_by": {"type": "string"},
                "include_pr_links": {"type": "boolean"},
            },
        },
    },
    {
        "name": "releasebutler.create_release",
        "description": "Create a new GitHub release and optionally upload local asset paths.",
        "annotations": {"openWorldHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["repo", "tag", "notes"],
            "properties": {
                "repo": {"type": "string"},
                "tag": {"type": "string"},
                "notes": {"type": "string"},
                "assets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional local file paths on the host to upload as release assets.",
                },
                "draft": {"type": "boolean"},
                "prerelease": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "provenance_manifest": {"type": "boolean"},
                "confirmation_token": {"type": "string"},
            },
        },
    },
    {
        "name": "core.get_job",
        "description": "Get a job by ID.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {"job_id": {"type": "string"}},
        },
    },
    {
        "name": "core.list_receipts",
        "description": "List receipt history.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {"operation": {"type": "string"}},
        },
    },
    {
        "name": "core.health",
        "description": "Return service health and configuration summary.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {"type": "object", "properties": {}},
    },
]

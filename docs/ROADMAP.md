# OmniAudit MCP Roadmap

## Current milestone
Enterprise Hardening Pass 2 is implemented:
1. S3/MinIO dual-read, S3-write object storage.
2. Release compare + upload hardening.
3. Structured logs, OTLP hooks, Prometheus metrics.

## Wave 1 Feature Expansion (in progress)
Execution order:
1. SiteLint
2. AuditLens
3. Release Butler

### SiteLint
1. Auth profile-based scans (`auth_profile_id`).
2. Deterministic crawl budgets and entry path support.
3. Multi-page evidence pack + zip report export.
4. Baseline comparison (`baseline_scan_id`) for delta tracking.

### AuditLens
1. Parser profile strategy (`auto`, `deterministic`, `console`, `lighthouse`).
2. Dedupe strategies and confidence calibration.
3. Issue drafting extensions (`assignees`, `milestone`, `template_id`).
4. Deterministic, file-anchored patch preview.

### Release Butler
1. Advanced notes grouping (`type`, `scope`, `author`).
2. Optional PR link rendering in notes.
3. Draft/prerelease/dry-run release options.
4. Optional provenance manifest generation for assets.

## Next milestones
1. Wave 2: stronger parser ecosystem and richer SiteLint authenticated journey coverage.
2. Wave 3: production telemetry dashboards and incident simulation playbooks.
3. Public alpha stabilization: documentation, release cadence, and contributor onboarding maturity.

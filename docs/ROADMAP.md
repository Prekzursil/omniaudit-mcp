# OmniAudit MCP Roadmap

## Current milestone
Enterprise Hardening Pass 2 is implemented:
1. S3/MinIO dual-read, S3-write object storage.
2. Release compare + upload hardening.
3. Structured logs, OTLP hooks, Prometheus metrics.

## Wave 1 Feature Expansion (complete)
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

## Wave 2+3 Program (in progress)

1. SiteLint wave 2 (additive):
   - `max_depth`, `crawl_strategy`, include/exclude pattern filtering, optional console/network snapshots.
   - `auth_journey_id` propagation and SARIF report format support.
   - baseline regression summary with new/resolved finding buckets.
2. AuditLens wave 2 (additive):
   - parser profile versioning and confidence profile controls.
   - deterministic merge-window handling, finding clusters, and ownership suggestions metadata.
   - issue drafting metadata extensions and `dry_run`.
3. Release Butler wave 2 (additive):
   - note templating, author/check inclusion controls, optional commit caps.
   - channel metadata, retryable asset uploads, publish timeout support.
   - enriched outputs (`upload_attempts`, `checks_summary`, `provenance_ref`).
4. Wave 3 cross-cutting:
   - observability dashboard/alert baseline docs.
   - incident drill scripts for GitHub outage, S3 unavailability, and worker restart behavior.

## Later milestones
1. Public alpha stabilization: documentation, release cadence, and contributor onboarding maturity.
2. Multi-tenant auth and policy partitioning (post single-operator v1).

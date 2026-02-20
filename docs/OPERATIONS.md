# Operations Runbook

## Environment setup

1. Copy env template:

```bash
cp .env.example .env
```

2. Set GitHub credentials:

- PAT mode:
  - `GITHUB_AUTH_MODE=pat`
  - `GITHUB_PAT=<token>`
- App mode:
  - `GITHUB_AUTH_MODE=app`
  - `GITHUB_APP_ID=<id>`
  - `GITHUB_APP_INSTALLATION_ID=<installation_id>`
  - `GITHUB_APP_PRIVATE_KEY=<PEM>`

3. Configure policy controls:

- `REPO_WRITE_ALLOWLIST`
- `URL_ALLOWLIST`
- `URL_DENYLIST`

4. Configure object store mode:

- Local mode (default):
  - `OBJECT_STORE_BACKEND=local`
- S3/MinIO mode:
  - `OBJECT_STORE_BACKEND=s3`
  - `OBJECT_STORE_BUCKET=omniaudit`
  - `OBJECT_STORE_PREFIX=omniaudit`
  - `S3_ENDPOINT_URL=http://minio:9000`
  - `S3_FORCE_PATH_STYLE=true`
  - `S3_ACCESS_KEY_ID=...`
  - `S3_SECRET_ACCESS_KEY=...`

5. Configure observability:

- Logs:
  - `LOG_FORMAT=json` or `LOG_FORMAT=plain`
- Optional traces:
  - `OTEL_ENABLED=true`
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces`
- Metrics:
  - `PROMETHEUS_ENABLED=true`

## Start services

```bash
docker compose up --build
```

## API checks

- Health: `GET /healthz`
- Tool list: `tools/list` via `/mcp`
- Dashboard state: `GET /ui/state`
- Metrics: `GET /metrics` (if enabled)

## Object store checks

Verify S3 write path (in `OBJECT_STORE_BACKEND=s3`):

1. Trigger a tool that stores immutable output (`auditlens.fetch_evidence`, `sitelint.start_scan`, or any receipt-emitting write tool).
2. Inspect returned refs:
   - new refs should be `s3://...`
3. Confirm legacy refs still resolve:
   - existing local-path `result_ref` rows should remain readable via dual-read fallback.

MinIO verification example:

```bash
docker compose exec minio mc alias set local http://127.0.0.1:9000 minioadmin minioadmin
docker compose exec minio mc ls local/omniaudit
```

## Backups

Back up persistent data:

- `data/` (objects, reports, key material)
- Postgres volume (`pg_data`)
- MinIO volume (`minio_data`) when using S3 backend mode

## Incident triage

1. Inspect API logs and worker logs.
2. Query receipts via `core.list_receipts`.
3. Inspect latest audit log rows in DB for `request_id`, `tool_name`, `inputs_hash`.
4. Check rate-limit settings if write/scan operations are blocked unexpectedly.
5. If S3 backend enabled, verify bucket reachability and credentials.

## S3 troubleshooting

- `OBJECT_STORE_BUCKET is required...`:
  - set `OBJECT_STORE_BUCKET` when `OBJECT_STORE_BACKEND=s3`.
- Auth failures (`AccessDenied`, `InvalidAccessKeyId`):
  - verify `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`.
- Endpoint failures:
  - verify `S3_ENDPOINT_URL`.
  - for MinIO use `S3_FORCE_PATH_STYLE=true`.

## OTLP troubleshooting

- Trace pipeline does not initialize:
  - verify `OTEL_ENABLED=true`.
  - verify `OTEL_EXPORTER_OTLP_ENDPOINT`.
  - inspect logs for exporter/instrumentation errors.
- Fast smoke check:
  - call `/healthz` and one MCP tool.
  - confirm spans arrive at collector.

## Smoke cleanup policy

- Keep the latest PASS evidence release/tag/assets for each hardening wave.
- Failed intermediate smoke releases/tags can be deleted from GitHub after investigation.
- Do not delete local smoke artifacts under `artifacts/smoke/` unless storage pressure requires it.
- Preserve `summary.json` and raw MCP responses for retained smoke evidence runs.
- Mark retained evidence release notes with `SMOKE-EVIDENCE`.

Cleanup example:

```bash
gh release delete smoke/v<failed-tag>-hardening-pass2 --repo Prekzursil/omniaudit-mcp --yes --cleanup-tag
gh release list --repo Prekzursil/omniaudit-mcp | head -n 20
```

## Metrics scrape example

Prometheus `scrape_configs` entry:

```yaml
- job_name: omniaudit-mcp
  metrics_path: /metrics
  static_configs:
    - targets: ["omniaudit-api:8080"]
```

## Secret rotation

- Rotate `WRITE_CONFIRMATION_SECRET` and restart API.
- Rotate `ENVELOPE_MASTER_KEY_FILE` using a maintenance script that re-encrypts stored credential values.

## Incident drills

Use these drills before production changes to validate degraded-mode behavior:

- `scripts/drills/drill_github_api_outage.sh`
- `scripts/drills/drill_s3_unavailability.sh`
- `scripts/drills/drill_worker_restart_resume.sh`

Each drill writes evidence under `artifacts/drills/<timestamp>/`.

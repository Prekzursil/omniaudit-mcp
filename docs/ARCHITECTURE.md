# Architecture

## Components

1. MCP API (`apps/mcp_server/main.py`)
- Handles JSON-RPC methods `initialize`, `tools/list`, `tools/call`.
- Returns both `content` and `structuredContent` for tool responses.
- Serves lightweight in-ChatGPT dashboard endpoints (`/ui`, `/ui/state`).
- Exposes Prometheus metrics at `/metrics` when enabled.
- Adds request context middleware for request ID propagation.

2. Runtime (`packages/omniaudit/mcp/runtime.py`)
- Dependency composition root.
- Policy checks, risk confirmations, rate limits, audit logging, receipts.
- Dispatches tool calls to module services.
- Emits tool call telemetry (structured logs + metrics).

3. Modules
- `AuditLens`: GitHub workflow run discovery, artifact retrieval, finding parsing, issue creation.
- `SiteLint`: URL scan job orchestration and report export.
- `Release Butler`: release metadata/asset retrieval, checksum verification, tag-compare note generation, release creation with local asset upload.

4. Storage
- SQL tables (`jobs`, `receipts`, `audit_logs`, `secret_credentials`).
- Object store abstraction:
  - `LocalObjectStore` for filesystem refs
  - `S3ObjectStore` for S3/MinIO refs (`s3://bucket/key`)
  - `DualReadObjectStore` for dual-read, S3-write rollout
- In `OBJECT_STORE_BACKEND=s3`:
  - writes go to S3 immutable keys (`<prefix>/<sha256>...`)
  - reads support both new S3 refs and legacy local path refs

5. Worker (`services/worker/tasks.py`)
- Optional asynchronous SiteLint execution through Celery + Redis.
- Uses the same object-store backend strategy as API runtime.

6. Observability (`packages/omniaudit/observability`)
- Logging:
  - JSON formatter fields: `timestamp`, `level`, `request_id`, `tool`, `module`, `duration_ms`, `status`, `error`
- Tracing:
  - OpenTelemetry FastAPI + HTTPX instrumentation
  - OTLP exporter when enabled
- Metrics:
  - `omniaudit_tool_calls_total{tool,status}`
  - `omniaudit_tool_latency_seconds{tool}`
  - `omniaudit_write_gate_denied_total{tool}`
  - `omniaudit_rate_limit_denied_total{bucket}`

## Security model

- Read/write separation at tool definition level.
- Write operations require a confirmation token (short-lived HMAC token bound to operation + payload).
- Repo and URL policy enforcement before execution.
- Input hashes and immutable output refs logged for traceability.

## Data model contracts

- `JobRef`: `job_id`, `module`, `status`, `progress`, `started_at`, `finished_at`
- `Receipt`: `receipt_id`, `operation`, `inputs_hash`, `actor`, `created_at`, `result_ref`
- `Finding`: `finding_id`, `severity`, `category`, `title`, `confidence`, `suggested_fix`, `evidence_refs`

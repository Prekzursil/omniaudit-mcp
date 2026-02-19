# Security Notes

## Current controls

- Confirmation token required for write tools:
  - `auditlens.create_issue`
  - `sitelint.export_report`
  - `releasebutler.create_release`
- Policy checks for repositories and URLs.
- In-memory rate limiting for write/scan surfaces.
- Immutable receipt and audit references.
- Immutable object content addressing:
  - local refs use `sha256` file names
  - S3 refs use `s3://<bucket>/<prefix>/<sha256>...`
- Dual-read, S3-write strategy prevents legacy reference breakage during backend cutover.
- Structured logs include operation metadata with request IDs.

## Recommended hardening for internet-facing deployment

- Put `/mcp` behind reverse proxy TLS.
- Enable API key mode (`MCP_AUTH_MODE=api_key`) or mTLS.
- Restrict allowed outbound network destinations at host/firewall layer.
- Run with least privilege filesystem permissions on `data/`.
- Add external SIEM shipping for audit logs.

## Telemetry data sensitivity

- Logs:
  - avoid logging secrets, PATs, private keys, or full tokenized payloads.
  - keep to request metadata, tool names, status, and latency.
- Metrics:
  - keep labels low-cardinality (`tool`, `status`, `bucket`) to prevent cardinality abuse.
- Traces:
  - OTLP export may carry URL and API path metadata; route to trusted collectors only.
  - treat trace storage as operationally sensitive data.

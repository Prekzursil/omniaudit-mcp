# Security Policy

## Reporting a Vulnerability
Please open a private security advisory in GitHub for this repository, or contact the maintainer directly if private advisories are unavailable in your context.

When reporting, include:
1. Affected component(s) and version/commit.
2. Reproduction steps.
3. Impact assessment.
4. Suggested mitigation if known.

## Scope
This project includes:
1. MCP server surfaces (`/mcp`, `/metrics`, `/healthz`).
2. Worker execution path and queue integration.
3. GitHub API integration and release operations.
4. Object storage adapters and receipt/audit persistence.

## Hardening Notes
Detailed operational and telemetry guidance is documented in `docs/SECURITY.md`.

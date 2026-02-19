# Contributing to OmniAudit MCP

## Development Setup
1. Create virtual environment:
```bash
uv venv .venv
```
2. Install dependencies:
```bash
uv pip install --python .venv/bin/python -e '.[test]'
```
3. Bootstrap local data:
```bash
./scripts/bootstrap.sh
```
4. Run the API:
```bash
PYTHONPATH=packages:apps:services .venv/bin/uvicorn mcp_server.main:app --host 0.0.0.0 --port 8080
```

## Running Checks
1. Lint:
```bash
.venv/bin/python -m ruff check .
```
2. Tests:
```bash
TMPDIR=/tmp TEMP=/tmp TMP=/tmp .venv/bin/pytest -q -s
```

## Pull Requests
1. Keep MCP tool names and existing required arguments backward-compatible.
2. Add tests for behavior changes and optional argument additions.
3. Include docs updates for new env vars, tool args, or operational workflows.
4. Use focused commits with clear scope.

## Smoke Validation
For hardening checks against live services:
```bash
./scripts/smoke_hardening_pass2.sh
```

Smoke artifacts are written to `artifacts/smoke/<timestamp>/`.

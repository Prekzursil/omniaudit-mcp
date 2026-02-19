PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
PYPATH ?= packages:apps:services

.PHONY: test lint run compose-up smoke-pass2

test:
	TMPDIR=/tmp TEMP=/tmp TMP=/tmp $(PYTEST) -q -s

lint:
	$(RUFF) check .

run:
	PYTHONPATH=$(PYPATH) $(UVICORN) mcp_server.main:app --host 0.0.0.0 --port 8080

compose-up:
	docker compose up --build

smoke-pass2:
	./scripts/smoke_hardening_pass2.sh

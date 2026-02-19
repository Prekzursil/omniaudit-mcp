from __future__ import annotations

import contextvars
import json
import logging
from datetime import UTC, datetime

request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id_context", default=None
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_context.get(),
            "tool": getattr(record, "tool", None),
            "module": getattr(record, "module_name", None) or getattr(record, "module", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "status": getattr(record, "status", None),
            "error": getattr(record, "error", None),
        }
        return json.dumps(payload)


def configure_logging(format_name: str = "json") -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if root.handlers:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    handler = logging.StreamHandler()
    if format_name == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root.addHandler(handler)

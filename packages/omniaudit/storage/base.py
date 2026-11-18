from __future__ import annotations

from typing import Any, Protocol


class ObjectStore(Protocol):
    def put_json_immutable(self, document: dict[str, Any]) -> str:
        """Store a JSON document immutably; return its content-addressed ref."""

    def put_bytes_immutable(self, content: bytes, suffix: str = ".bin") -> str:
        """Store raw bytes immutably; return its content-addressed ref."""

    def read_text(self, ref: str) -> str:
        """Return the stored document's text content."""

    def read_bytes(self, ref: str) -> bytes:
        """Return the stored object's raw bytes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from omniaudit.storage.base import ObjectStore


@dataclass(slots=True)
class DualReadObjectStore(ObjectStore):
    primary: ObjectStore
    fallback: ObjectStore

    def put_json_immutable(self, document: dict[str, Any]) -> str:
        return self.primary.put_json_immutable(document)

    def put_bytes_immutable(self, content: bytes, suffix: str = ".bin") -> str:
        return self.primary.put_bytes_immutable(content, suffix=suffix)

    def read_text(self, ref: str) -> str:
        if ref.startswith("s3://"):
            return self.primary.read_text(ref)
        try:
            return self.fallback.read_text(ref)
        except Exception:
            return self.primary.read_text(ref)

    def read_bytes(self, ref: str) -> bytes:
        if ref.startswith("s3://"):
            return self.primary.read_bytes(ref)
        try:
            return self.fallback.read_bytes(ref)
        except Exception:
            return self.primary.read_bytes(ref)

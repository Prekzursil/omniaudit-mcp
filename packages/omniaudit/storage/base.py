from __future__ import annotations

from typing import Protocol


class ObjectStore(Protocol):
    def put_json_immutable(self, document: dict) -> str:
        ...

    def put_bytes_immutable(self, content: bytes, suffix: str = ".bin") -> str:
        ...

    def read_text(self, ref: str) -> str:
        ...

    def read_bytes(self, ref: str) -> bytes:
        ...

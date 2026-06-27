from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omniaudit.storage.base import ObjectStore


@dataclass(slots=True)
class LocalObjectStore(ObjectStore):
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put_json_immutable(self, document: dict[str, Any]) -> str:
        body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        path = self.root / f"{digest}.json"
        if not path.exists():
            path.write_bytes(body)
        return str(path)

    def put_bytes_immutable(self, content: bytes, suffix: str = ".bin") -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self.root / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(content)
        return str(path)

    def read_text(self, ref: str) -> str:
        return self.read_bytes(ref).decode("utf-8")

    def read_bytes(self, ref: str) -> bytes:
        return Path(ref).read_bytes()

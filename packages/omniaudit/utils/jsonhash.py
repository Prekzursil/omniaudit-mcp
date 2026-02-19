from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_hash(document: dict[str, Any]) -> str:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

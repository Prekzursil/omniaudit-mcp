from __future__ import annotations

import hashlib


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_checksum(content: bytes, expected_hex: str) -> bool:
    normalized = expected_hex.strip().lower()
    return sha256_hex(content) == normalized

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


def _canonical_payload(operation: str, payload: dict[str, Any], issued_at: int) -> bytes:
    document = {
        "operation": operation,
        "payload": payload,
        "issued_at": issued_at,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(slots=True)
class ConfirmationService:
    secret: str
    ttl_seconds: int = 600

    def issue_token(self, operation: str, payload: dict[str, Any]) -> str:
        issued_at = int(time.time())
        body = _canonical_payload(operation, payload, issued_at)
        signature = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).digest()

        token_document = {
            "issued_at": issued_at,
            "sig": base64.urlsafe_b64encode(signature).decode("ascii"),
        }
        return base64.urlsafe_b64encode(
            json.dumps(token_document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

    def verify_token(self, operation: str, payload: dict[str, Any], token: str | None) -> bool:
        if not token:
            return False

        try:
            decoded = json.loads(base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8"))
            issued_at = int(decoded["issued_at"])
            if int(time.time()) - issued_at > self.ttl_seconds:
                return False

            expected = hmac.new(
                self.secret.encode("utf-8"),
                _canonical_payload(operation, payload, issued_at),
                hashlib.sha256,
            ).digest()
            provided = base64.urlsafe_b64decode(decoded["sig"].encode("ascii"))
            return hmac.compare_digest(expected, provided)
        except Exception:
            return False

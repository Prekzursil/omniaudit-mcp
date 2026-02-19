from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from omniaudit.models.db import SecretCredential
from omniaudit.security.envelope import EnvelopeEncryption


@dataclass(slots=True)
class SecretCredentialStore:
    session_factory: type
    envelope: EnvelopeEncryption

    def get_auth_profile(self, credential_name: str) -> dict[str, Any] | None:
        with self.session_factory() as session:
            row = session.execute(
                select(SecretCredential).where(SecretCredential.credential_name == credential_name)
            ).scalar_one_or_none()
            if not row:
                return None
            decrypted = self.envelope.decrypt_secret(row.encrypted_value)
            payload = json.loads(decrypted)
            if not isinstance(payload, dict):
                return None
            return payload

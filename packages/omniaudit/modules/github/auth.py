from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx
import jwt


class GitHubAuthProvider(Protocol):
    def authorization_header(self) -> str: ...


@dataclass(slots=True)
class PATAuthProvider:
    token: str

    def authorization_header(self) -> str:
        return f"Bearer {self.token}"


@dataclass(slots=True)
class GitHubAppAuthProvider:
    app_id: str
    installation_id: str
    private_key_pem: str
    api_base: str = "https://api.github.com"
    _cached_token: str | None = field(default=None, init=False)
    _cached_expiry_epoch: int = field(default=0, init=False)

    def authorization_header(self) -> str:
        if self._cached_token and time.time() < self._cached_expiry_epoch - 60:
            return f"Bearer {self._cached_token}"

        jwt_token = self._create_app_jwt()
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                f"{self.api_base}/app/installations/{self.installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response.raise_for_status()
            payload = response.json()
            self._cached_token = payload["token"]
            expires_at = payload["expires_at"]

        expiry_epoch = int(time.mktime(time.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ")))
        self._cached_expiry_epoch = expiry_epoch
        return f"Bearer {self._cached_token}"

    def _create_app_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 540,
            "iss": self.app_id,
        }
        encoded = jwt.encode(payload, self.private_key_pem, algorithm="RS256")
        if isinstance(encoded, bytes):
            return encoded.decode("utf-8")
        return encoded

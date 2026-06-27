from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class PolicyViolation(ValueError):
    """Raised when a policy check fails."""


@dataclass(slots=True)
class PolicyEngine:
    repo_allowlist: set[str]
    url_allowlist: set[str]
    url_denylist: set[str]

    def require_repo_write_allowed(self, repo: str) -> None:
        if self.repo_allowlist and repo not in self.repo_allowlist:
            raise PolicyViolation(f"Repo '{repo}' is not in write allowlist")

    def require_url_allowed(self, url: str) -> None:
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        for denied in self.url_denylist:
            if denied and denied.lower() in host:
                raise PolicyViolation(f"URL host '{host}' is denylisted")

        if self.url_allowlist and not any(
            allowed.lower() in host for allowed in self.url_allowlist
        ):
            raise PolicyViolation(f"URL host '{host}' is not in allowlist")

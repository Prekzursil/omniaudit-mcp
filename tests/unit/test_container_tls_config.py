from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_api_container_sets_system_ca_bundle() -> None:
    content = _read("infra/Dockerfile.api")
    assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in content
    assert "ca-certificates" in content


def test_worker_container_sets_system_ca_bundle() -> None:
    content = _read("infra/Dockerfile.worker")
    assert "SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt" in content
    assert "ca-certificates" in content

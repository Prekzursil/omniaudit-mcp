from __future__ import annotations

import time

import pytest
from omniaudit.core.policy import PolicyEngine, PolicyViolation
from omniaudit.security.confirmation import ConfirmationService


def test_repo_write_allowlist() -> None:
    engine = PolicyEngine(repo_allowlist={"o/allowed"}, url_allowlist=set(), url_denylist=set())
    engine.require_repo_write_allowed("o/allowed")  # allowed -> no raise
    with pytest.raises(PolicyViolation, match="not in write allowlist"):
        engine.require_repo_write_allowed("o/blocked")
    # Empty allowlist permits everything.
    PolicyEngine(
        repo_allowlist=set(), url_allowlist=set(), url_denylist=set()
    ).require_repo_write_allowed("any/repo")


def test_url_denylist_and_allowlist() -> None:
    engine = PolicyEngine(
        repo_allowlist=set(),
        url_allowlist={"example.com"},
        url_denylist={"evil.com"},
    )
    engine.require_url_allowed("https://example.com/path")  # allowed
    with pytest.raises(PolicyViolation, match="denylisted"):
        engine.require_url_allowed("https://evil.com")
    with pytest.raises(PolicyViolation, match="not in allowlist"):
        engine.require_url_allowed("https://other.com")


def test_confirmation_token_roundtrip_and_failures() -> None:
    svc = ConfirmationService(secret="s", ttl_seconds=600)
    payload = {"a": 1}
    token = svc.issue_token("op", payload)
    assert svc.verify_token("op", payload, token) is True
    # Wrong payload -> signature mismatch.
    assert svc.verify_token("op", {"a": 2}, token) is False
    # Missing token.
    assert svc.verify_token("op", payload, None) is False
    # Malformed token -> exception branch.
    assert svc.verify_token("op", payload, "!!!not-base64!!!") is False


def test_confirmation_token_expired(monkeypatch) -> None:
    svc = ConfirmationService(secret="s", ttl_seconds=1)
    token = svc.issue_token("op", {"a": 1})
    monkeypatch.setattr(time, "time", lambda: 10**12)
    assert svc.verify_token("op", {"a": 1}, token) is False

import pytest
from omniaudit.core.policy import PolicyEngine, PolicyViolation


def test_repo_allowlist_blocks_unapproved_repo() -> None:
    policy = PolicyEngine(repo_allowlist={"Prekzursil/AdrianaArt"}, url_allowlist=set(), url_denylist=set())

    with pytest.raises(PolicyViolation):
        policy.require_repo_write_allowed("Prekzursil/RandomRepo")


def test_url_denylist_blocks_scan() -> None:
    policy = PolicyEngine(repo_allowlist=set(), url_allowlist=set(), url_denylist={"localhost"})

    with pytest.raises(PolicyViolation):
        policy.require_url_allowed("http://localhost:3000")

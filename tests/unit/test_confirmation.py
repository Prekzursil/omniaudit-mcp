from omniaudit.security.confirmation import ConfirmationService


def test_confirmation_round_trip() -> None:
    svc = ConfirmationService(secret="top-secret", ttl_seconds=600)
    payload = {"repo": "Prekzursil/AdrianaArt", "operation": "auditlens.create_issue"}
    token = svc.issue_token("auditlens.create_issue", payload)

    assert svc.verify_token("auditlens.create_issue", payload, token) is True


def test_confirmation_rejects_mismatched_payload() -> None:
    svc = ConfirmationService(secret="top-secret", ttl_seconds=600)
    payload = {"repo": "Prekzursil/AdrianaArt", "operation": "auditlens.create_issue"}
    token = svc.issue_token("auditlens.create_issue", payload)

    assert svc.verify_token(
        "auditlens.create_issue",
        {"repo": "Prekzursil/env-inspector", "operation": "auditlens.create_issue"},
        token,
    ) is False

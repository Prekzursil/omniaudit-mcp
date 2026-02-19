from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from omniaudit.security.confirmation import ConfirmationService


@dataclass(slots=True)
class RiskGateResult:
    allowed: bool
    response: dict[str, Any] | None = None


@dataclass(slots=True)
class RiskGate:
    confirmation_service: ConfirmationService

    def check_write(
        self,
        operation: str,
        payload: dict[str, Any],
        confirmation_token: str | None,
    ) -> RiskGateResult:
        if self.confirmation_service.verify_token(operation, payload, confirmation_token):
            return RiskGateResult(allowed=True)

        token = self.confirmation_service.issue_token(operation, payload)
        return RiskGateResult(
            allowed=False,
            response={
                "requires_confirmation": True,
                "risk_level": "high",
                "confirmation_token": token,
                "message": "Re-run with confirmation_token to execute write operation.",
            },
        )

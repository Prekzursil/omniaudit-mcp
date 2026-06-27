from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from omniaudit.models.db import AuditLog
from omniaudit.utils.jsonhash import canonical_hash


@dataclass(slots=True)
class AuditLogger:
    session_factory: sessionmaker[Session]

    def append(
        self, request_id: str, tool_name: str, inputs: dict[str, Any], output_ref: str
    ) -> None:
        with self.session_factory() as session:
            row = AuditLog(
                request_id=request_id,
                tool_name=tool_name,
                inputs_hash=canonical_hash(inputs),
                output_ref=output_ref,
            )
            session.add(row)
            session.commit()

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from omniaudit.models.db import Receipt
from omniaudit.storage.base import ObjectStore
from omniaudit.utils.jsonhash import canonical_hash


@dataclass(slots=True)
class ReceiptStore:
    session_factory: sessionmaker[Session]
    object_store: ObjectStore

    def create_receipt(
        self, operation: str, actor: str, inputs: dict[str, Any], result: dict[str, Any]
    ) -> Receipt:
        inputs_hash = canonical_hash(inputs)
        result_ref = self.object_store.put_json_immutable(result)
        receipt_id = f"rcpt_{uuid4().hex}"

        with self.session_factory() as session:
            receipt = Receipt(
                receipt_id=receipt_id,
                operation=operation,
                inputs_hash=inputs_hash,
                actor=actor,
                result_ref=result_ref,
                created_at=datetime.now(UTC),
            )
            session.add(receipt)
            session.commit()
            session.refresh(receipt)
            return receipt

    def list_receipts(self, operation: str | None = None) -> list[Receipt]:
        from sqlalchemy import select

        with self.session_factory() as session:
            stmt = select(Receipt).order_by(Receipt.created_at.desc())
            if operation:
                stmt = stmt.where(Receipt.operation == operation)
            return list(session.execute(stmt).scalars().all())

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from omniaudit.models.db import Job


@dataclass(slots=True)
class JobStore:
    session_factory: sessionmaker[Session]

    def create_or_get_job(
        self,
        module: str,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> Job:
        with self.session_factory() as session:
            existing = session.execute(
                select(Job).where(Job.idempotency_key == idempotency_key)
            ).scalar_one_or_none()
            if existing:
                return existing

            new_job = Job(
                job_id=f"job_{uuid4().hex}",
                module=module,
                operation=operation,
                idempotency_key=idempotency_key,
                payload=payload,
                status="queued",
                progress=0.0,
            )
            session.add(new_job)
            try:
                session.commit()
            except IntegrityError:  # pragma: no cover - concurrent-insert race, not deterministically reproducible in-process
                session.rollback()
                existing = session.execute(
                    select(Job).where(Job.idempotency_key == idempotency_key)
                ).scalar_one()
                return existing

            session.refresh(new_job)
            return new_job

    def get_job(self, job_id: str) -> Job | None:
        with self.session_factory() as session:
            return session.execute(select(Job).where(Job.job_id == job_id)).scalar_one_or_none()

    def set_job_status(
        self,
        job_id: str,
        status: str,
        progress: float,
        result_ref: str | None = None,
    ) -> Job | None:
        with self.session_factory() as session:
            job = session.execute(select(Job).where(Job.job_id == job_id)).scalar_one_or_none()
            if not job:
                return None
            job.status = status
            job.progress = progress
            if result_ref is not None:
                job.result_ref = result_ref
            session.commit()
            session.refresh(job)
            return job

    def list_jobs(self, module: str | None = None, limit: int = 50) -> list[Job]:
        with self.session_factory() as session:
            stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
            if module:
                stmt = stmt.where(Job.module == module)
            return list(session.execute(stmt).scalars().all())


def default_idempotency_key(operation: str, payload: dict[str, Any]) -> str:
    body = json.dumps({"operation": operation, "payload": payload}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(body).hexdigest()

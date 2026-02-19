from omniaudit.models.db import Base
from omniaudit.storage.jobs import JobStore
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_job_idempotency_returns_same_job_for_same_key() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)

    store = JobStore(session_factory)
    first = store.create_or_get_job(
        module="sitelint",
        operation="sitelint.start_scan",
        idempotency_key="abc123",
        payload={"url": "https://example.com"},
    )
    second = store.create_or_get_job(
        module="sitelint",
        operation="sitelint.start_scan",
        idempotency_key="abc123",
        payload={"url": "https://example.com"},
    )

    assert first.job_id == second.job_id

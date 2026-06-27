from __future__ import annotations

from pathlib import Path

import pytest
from omniaudit.core.settings import settings
from worker import tasks as tasks_module
from worker.worker import health


def test_health_task() -> None:
    assert health() == {"status": "ok"}


def test_dispatch_sitelint_scan(monkeypatch) -> None:
    captured = {}

    def fake_delay(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(tasks_module.run_sitelint_scan_task, "delay", fake_delay)
    tasks_module.dispatch_sitelint_scan("job-1", {"url": "https://x.com"})
    assert captured == {"job_id": "job-1", "payload": {"url": "https://x.com"}}


def test_build_object_store_local(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "object_store_root", tmp_path / "objs")
    monkeypatch.setattr(settings, "object_store_backend", "local")
    store = tasks_module._build_object_store()
    assert store.__class__.__name__ == "LocalObjectStore"


def test_build_object_store_s3_requires_bucket(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "object_store_root", tmp_path / "objs")
    monkeypatch.setattr(settings, "object_store_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", None)
    with pytest.raises(RuntimeError, match="OBJECT_STORE_BUCKET"):
        tasks_module._build_object_store()


def test_build_object_store_s3_dual(monkeypatch, tmp_path) -> None:
    import boto3

    monkeypatch.setattr(settings, "object_store_root", tmp_path / "objs")
    monkeypatch.setattr(settings, "object_store_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", "bkt")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: object())
    store = tasks_module._build_object_store()
    assert store.__class__.__name__ == "DualReadObjectStore"


def test_run_sitelint_scan_task(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "object_store_root", tmp_path / "objs")
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "reports_root", tmp_path / "reports")
    monkeypatch.setattr(
        settings, "database_url", f"sqlite+pysqlite:///{(tmp_path / 'w.db').as_posix()}"
    )

    # Initialize the schema for the temp DB.
    from omniaudit.storage.engine import create_db_engine, initialize_database

    initialize_database(create_db_engine(settings.database_url))

    # Seed a queued job so set_job_status finds a row.
    from omniaudit.storage.engine import create_session_factory
    from omniaudit.storage.jobs import JobStore

    jobs = JobStore(create_session_factory(create_db_engine(settings.database_url)))
    job = jobs.create_or_get_job(
        "sitelint", "sitelint.start_scan", "wkey", {"url": "https://x.com"}
    )

    monkeypatch.setattr(
        tasks_module,
        "run_sitelint_scan",
        lambda *a, **k: {"findings": [], "metrics": {}, "artifacts": {}, "pages": []},
    )

    result = tasks_module.run_sitelint_scan_task(job.job_id, {"url": "https://x.com"})
    assert result["job_id"] == job.job_id
    assert result["result_ref"]
    assert isinstance(Path(settings.reports_root / job.job_id), Path)

from __future__ import annotations

from pathlib import Path
from typing import Any

from celery import Celery
from omniaudit.core.settings import settings
from omniaudit.modules.sitelint.scanner import run_sitelint_scan
from omniaudit.storage.dual import DualReadObjectStore
from omniaudit.storage.engine import create_db_engine, create_session_factory
from omniaudit.storage.jobs import JobStore
from omniaudit.storage.objects import LocalObjectStore
from omniaudit.storage.s3 import S3ObjectStore

celery_app = Celery("omniaudit_worker", broker=settings.redis_url, backend=settings.redis_url)


def dispatch_sitelint_scan(job_id: str, payload: dict[str, Any]) -> None:
    # celery's @task decorator is untyped, so .delay is invisible to the type checker
    run_sitelint_scan_task.delay(job_id=job_id, payload=payload)  # type: ignore[attr-defined]


def _build_object_store():
    local_store = LocalObjectStore(settings.object_store_root)
    if settings.object_store_backend.lower().strip() != "s3":
        return local_store

    if not settings.object_store_bucket:
        raise RuntimeError("OBJECT_STORE_BUCKET is required when OBJECT_STORE_BACKEND=s3")

    s3_store = S3ObjectStore(
        bucket=settings.object_store_bucket,
        prefix=settings.object_store_prefix,
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region_name,
        force_path_style=settings.s3_force_path_style,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )
    return DualReadObjectStore(primary=s3_store, fallback=local_store)


@celery_app.task(name="omniaudit.sitelint.run_scan")
def run_sitelint_scan_task(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    jobs = JobStore(session_factory)
    object_store = _build_object_store()

    jobs.set_job_status(job_id, "running", 0.25)
    report = run_sitelint_scan(
        url=payload["url"],
        profile=payload.get("profile", "standard"),
        viewport_set=payload.get("viewport_set", "desktop_mobile"),
        report_dir=Path(settings.reports_root) / job_id,
    )
    result_ref = object_store.put_json_immutable(report)
    jobs.set_job_status(job_id, "completed", 1.0, result_ref=result_ref)
    return {"job_id": job_id, "result_ref": result_ref}

from __future__ import annotations

from .tasks import celery_app


@celery_app.task(name="omniaudit.health")
def health() -> dict[str, str]:
    return {"status": "ok"}

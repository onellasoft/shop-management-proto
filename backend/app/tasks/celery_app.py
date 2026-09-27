"""Celery application factory and singleton.

The Onella backend uses Celery for out-of-band work — primarily the
asynchronous append-only audit log the design calls for. Both the broker and
the result backend are Redis, sourced from ``settings.redis_url`` so the
configuration matches the rest of the stack and honors environment overrides.

Run a worker with::

    celery -A app.tasks.celery_app worker --loglevel=info

Task modules are eagerly imported via ``include`` so the worker registers them
on startup.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings


def create_celery() -> Celery:
    """Create and configure the Celery application.

    Broker and result backend both point at ``settings.redis_url``. Task
    modules are registered via ``include`` so a fresh worker discovers them.
    """
    app = Celery(
        "onella",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["app.tasks.audit_tasks"],
    )

    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        # Acknowledge tasks only after completion so a crashed worker's task is
        # redelivered rather than silently lost (at-least-once for audit writes).
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        result_expires=3600,
    )

    return app


# Module-level singleton used by workers (`-A app.tasks.celery_app`) and by
# request handlers that enqueue tasks.
celery_app = create_celery()

__all__ = ["celery_app", "create_celery"]

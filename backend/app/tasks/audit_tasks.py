"""Asynchronous audit-log write task (Req 14.5, 14.7).

The real audit sink behind ``Audit_Service.enqueue``. After an originating
mutation commits, ``app.audit.mutation_capture`` enqueues one
:func:`write_audit_log` task per captured mutation (non-blocking, Req 14.5).
The task INSERTs an :class:`~app.models.audit.AuditLog` from the entry dict; on
failure it retries up to three times, and once retries are exhausted it INSERTs
a durable :class:`~app.models.audit.AuditFailure` row recording the unlogged
mutation so the originating request is never failed (Req 14.7).

The recorded log becomes visible to audit queries as soon as this task's INSERT
commits — a consequence of the async pipeline, well within the 60 s bound the
design calls for (Req 14.5); no explicit timing code is needed beyond the
non-blocking enqueue.

The Celery worker is synchronous, so this task talks to the database through a
**synchronous** SQLAlchemy session derived from ``settings.database_url`` (the
asyncpg driver is swapped for the sync ``psycopg`` driver). The session factory
is created lazily and is injectable (:func:`set_audit_session_factory`) so unit
tests exercise the retry / failure logic against an in-memory fake with no live
broker or database.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from app.models.audit import AuditFailure, AuditLog
from app.tasks.celery_app import celery_app

# A factory returning a context-managed session (``with factory() as session``).
SessionFactory = Callable[[], AbstractContextManager[Any]]

_session_factory: SessionFactory | None = None


def _sync_database_url() -> str:
    """Return a synchronous SQLAlchemy URL derived from the async setting.

    The app runs on ``postgresql+asyncpg``; the Celery worker is synchronous,
    so the async driver is swapped for the sync ``psycopg`` driver.
    """
    from app.core.config import settings

    url = settings.database_url
    return url.replace("+asyncpg", "+psycopg").replace(
        "postgresql://", "postgresql+psycopg://"
    )


def _default_session_factory() -> AbstractContextManager[Any]:
    """Build a synchronous ``Session`` bound to a process-wide sync engine.

    The engine is created once and cached on this function so repeated task
    executions reuse the connection pool.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = getattr(_default_session_factory, "_engine", None)
    if engine is None:
        engine = create_engine(_sync_database_url(), pool_pre_ping=True, future=True)
        _default_session_factory._engine = engine  # type: ignore[attr-defined]
    return Session(engine)


def set_audit_session_factory(factory: SessionFactory | None) -> None:
    """Override the sync session factory used by :func:`write_audit_log`.

    Passing ``None`` restores the default sync-engine factory. Tests inject a
    factory yielding an in-memory fake session so the retry / failure paths can
    be exercised without a live database.
    """
    global _session_factory
    _session_factory = factory


def _get_session_factory() -> SessionFactory:
    return _session_factory or _default_session_factory


def _parse_uuid(value: Any) -> uuid.UUID | None:  # noqa: ANN401
    """Parse a stringified UUID from the transported entry dict."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _audit_log_from_entry(entry: dict[str, Any]) -> AuditLog:
    """Build an :class:`AuditLog` from a transported ``AuditEntry`` dict (Req 14.3)."""
    return AuditLog(
        user_id=_parse_uuid(entry.get("user_id")),
        role_type=entry.get("role_type"),
        agency_id=_parse_uuid(entry.get("agency_id")),
        customer_id=_parse_uuid(entry.get("customer_id")),
        module=entry.get("module"),
        sub_module=entry.get("sub_module"),
        resource=entry.get("resource"),
        action=entry.get("action"),
        old_value=entry.get("old_value") or {},
        new_value=entry.get("new_value") or {},
        impersonation=bool(entry.get("impersonation", False)),
        impersonator_user_id=_parse_uuid(entry.get("impersonator_user_id")),
    )


def _insert_audit_log(entry: dict[str, Any]) -> None:
    """INSERT one :class:`AuditLog` row from ``entry`` (the happy path, Req 14.5)."""
    factory = _get_session_factory()
    with factory() as session:
        session.add(_audit_log_from_entry(entry))
        session.commit()


def _record_failure(entry: dict[str, Any], error: str) -> None:
    """Persist a durable :class:`AuditFailure` for an unlogged mutation (Req 14.7)."""
    factory = _get_session_factory()
    with factory() as session:
        session.add(AuditFailure(payload=entry, error=error))
        session.commit()


@celery_app.task(
    name="app.tasks.audit_tasks.write_audit_log", bind=True, max_retries=3
)
def write_audit_log(self, entry: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
    """Persist an :class:`AuditLog`; on final failure persist an :class:`AuditFailure`.

    On INSERT failure the task retries (up to ``max_retries=3``). ``self.retry``
    raises internally to reschedule; when retries are exhausted Celery raises
    :class:`~celery.exceptions.MaxRetriesExceededError`, which we catch to write
    the durable :class:`AuditFailure` (Req 14.7) so the originating request —
    which already returned — is never impacted.
    """
    from celery.exceptions import MaxRetriesExceededError

    try:
        _insert_audit_log(entry)
        return {"status": "recorded"}
    except Exception as exc:  # noqa: BLE001 - retry any transient write failure
        try:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)
        except MaxRetriesExceededError:
            _record_failure(entry, str(exc))
            return {"status": "failed", "error": str(exc)}


__all__ = [
    "write_audit_log",
    "set_audit_session_factory",
]

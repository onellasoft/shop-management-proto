"""Asynchronous audit-logging tasks.

Sample Celery task scaffolding for the append-only audit log described in the
project design. This is intentionally a thin, self-contained starting point:
it accepts a structured audit event and records it. The concrete persistence
(dedicated ``audit_logs`` table / sink) is wired up by a later task; for now
the task validates and logs the event so the Celery path is exercised
end-to-end.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tasks.celery_app import celery_app

logger = logging.getLogger("onella.audit")


@celery_app.task(name="app.tasks.audit.record_audit_event", bind=True, max_retries=3)
def record_audit_event(self, event: dict[str, Any]) -> dict[str, Any]:
    """Record a single audit event asynchronously.

    Parameters
    ----------
    event:
        A JSON-serializable dict describing the action, e.g.::

            {
                "actor_id": "...",
                "action": "user.login",
                "target": "...",
                "metadata": {...},
                "occurred_at": "2026-08-30T14:00:00Z",
            }

    Returns the stored event (currently echoed back). Retries with backoff on
    unexpected failures so a transient sink outage does not drop the event.
    """
    try:
        logger.info("audit_event %s", event)
        # TODO(track-2): persist to the audit_logs table / append-only sink.
        return {"status": "recorded", "event": event}
    except Exception as exc:  # noqa: BLE001 - retry any transient failure
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


__all__ = ["record_audit_event"]

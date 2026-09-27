"""Mutation audit-logging subsystem (Req 14).

Groups the SQLAlchemy-driven mutation capture (Task 21.1), the append-only
service-layer guard (Task 21.3), and the enqueue-after-commit wiring that
hands captured entries to the async Celery write task (Task 21.2, see
``app.services.audit_service`` and ``app.tasks.audit_tasks``).
"""

from __future__ import annotations

from app.audit.mutation_capture import (
    AuditEntry,
    register_audit_listeners,
    register_audited_model,
    set_audit_scheduler,
    set_session_tenant_context,
)

__all__ = [
    "AuditEntry",
    "register_audit_listeners",
    "register_audited_model",
    "set_audit_scheduler",
    "set_session_tenant_context",
]

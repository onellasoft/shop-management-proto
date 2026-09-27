"""AuditLog and AuditFailure ORM models.

Back the **mutation audit logging** subsystem (Req 14). Every mutation
performed against the system is recorded as one append-only ``audit_logs`` row;
when the asynchronous recording exhausts its retries a durable ``audit_failures``
row is persisted instead so the originating request never fails (Req 14.7).

See design "Table Details → audit_logs" and "audit_failures" (and the ER
diagram ``AUDIT_LOGS``).

audit_logs (Req 14.1, 14.3, 14.4, 14.6):

* ``id``                   — UUID PK.
* ``user_id``              — UUID FK → ``users.id``; the actor who performed
  the mutation.
* ``role_type``            — varchar(20); the actor's role type at the time.
* ``agency_id``            — UUID nullable; the Agency identifier of the active
  ``TenantContext``. A **plain indexed UUID**, deliberately *not* an FK, so
  audit retention is decoupled from the lifecycle of the tenant row (the ER
  diagram lists it as a plain ``uuid`` on ``AUDIT_LOGS``).
* ``customer_id``          — UUID nullable; the Customer identifier of the
  active context. Plain indexed UUID (not an FK), same rationale as
  ``agency_id``.
* ``module`` / ``sub_module`` / ``resource`` / ``action`` — varchar; the
  permission-graph names identifying the mutated resource/action.
* ``old_value`` / ``new_value`` — jsonb; the before/after diff. For a create
  the old value is empty and for a delete the new value is empty — the
  emptiness is decided by the capture logic (Task 21); the column merely
  permits jsonb (Req 14.3).
* ``impersonation``        — boolean NOT NULL default ``false``; set true when
  the mutation happened during an active impersonation session (Req 14.4).
* ``impersonator_user_id`` — UUID nullable; the impersonator's id when
  ``impersonation`` is true (Req 14.4).
* ``created_at``           — timestamptz NOT NULL default ``now()``.

The table is **append-only** (Req 14.6): it therefore declares **only**
``created_at`` and does *not* use :class:`TimestampMixin` (which would add an
``updated_at`` refreshed on UPDATE — meaningless for a row that can never be
updated). The append-only invariant is enforced at the DB level by a trigger
rejecting UPDATE/DELETE (added in the migration) and complemented by a
service-layer guard (Task 21.3).

Indexes (design): ``ix_audit_created_at`` (created_at, DESC ordering applied in
the migration), ``ix_audit_agency`` (agency_id), ``ix_audit_customer``
(customer_id), ``ix_audit_user`` (user_id), ``ix_audit_action`` (action).

audit_failures (Req 14.7):

* ``id``         — UUID PK.
* ``payload``    — jsonb; the unrecorded ``AuditEntry``.
* ``error``      — text; the failure detail.
* ``created_at`` — timestamptz NOT NULL default ``now()``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.sql.sqltypes import TIMESTAMP

from app.db.base import Base


class AuditLog(Base):
    """An append-only record of one mutation (Req 14.1, 14.3, 14.4, 14.6)."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    role_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Tenant identifiers of the context under which the mutation ran. Plain
    # indexed UUIDs, NOT foreign keys (see module docstring / Req 14.1).
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    module: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sub_module: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    impersonation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    impersonator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        # created_at DESC — audit queries return newest first (Req 15.5). The
        # DESC ordering is applied in the migration via postgresql_ops; the
        # model declares the index over the same column so autogenerate stays
        # consistent (see the migration for the ordering nuance).
        Index("ix_audit_created_at", "created_at"),
        Index("ix_audit_agency", "agency_id"),
        Index("ix_audit_customer", "customer_id"),
        Index("ix_audit_user", "user_id"),
        Index("ix_audit_action", "action"),
    )


class AuditFailure(Base):
    """A durable record of an audit write that exhausted its retries (Req 14.7)."""

    __tablename__ = "audit_failures"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


__all__ = ["AuditLog", "AuditFailure"]

"""ImpersonationSession ORM model.

Backs the **impersonation session lifecycle** (Req 11). When a superadmin or
agencyadmin impersonates a tenant, one row records who is impersonating whom
and when the session started/ended.

See design "Table Details → impersonation_sessions":

* ``id``                      — UUID PK.
* ``impersonator_user_id``    — UUID FK → ``users.id``, NOT NULL; the actor.
* ``impersonated_agency_id``  — UUID FK → ``agencies.id``, nullable.
* ``impersonated_customer_id``— UUID FK → ``customers.id``, nullable.
* ``active``                  — boolean NOT NULL default ``true``.
* ``started_at``              — timestamptz NOT NULL default ``now()``.
* ``ended_at``                — timestamptz nullable; set when the session ends.
* ``created_at`` / ``updated_at`` — from :class:`TimestampMixin`.

Constraints / indexes (Req 11.4, 11.6):

* ``ck_impersonation_sessions_one_target`` — CHECK that **exactly one** of
  ``impersonated_agency_id`` / ``impersonated_customer_id`` is set (XOR). An
  impersonation always targets a single entity, never both nor neither.
* ``uq_impersonation_active_per_impersonator`` — a **partial** unique index
  over ``impersonator_user_id`` WHERE ``active`` is true, enforcing at most one
  active session per impersonator (Req 11.6).
* ``ix_impersonation_sessions_impersonator`` — index on
  ``impersonator_user_id`` for looking up an impersonator's active session.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.sql.sqltypes import TIMESTAMP

from app.db.base import Base
from app.db.mixins import TimestampMixin


class ImpersonationSession(TimestampMixin, Base):
    """A record of one impersonation session (Req 11.4, 11.6)."""

    __tablename__ = "impersonation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    impersonator_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    impersonated_agency_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agencies.id"),
        nullable=True,
    )
    impersonated_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customers.id"),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        # Exactly one impersonation target (XOR): agency xor customer.
        CheckConstraint(
            "(impersonated_agency_id IS NOT NULL) "
            "<> (impersonated_customer_id IS NOT NULL)",
            name="ck_impersonation_sessions_one_target",
        ),
        # At most one active session per impersonator (Req 11.6).
        Index(
            "uq_impersonation_active_per_impersonator",
            "impersonator_user_id",
            unique=True,
            postgresql_where=text("active"),
        ),
        Index(
            "ix_impersonation_sessions_impersonator",
            "impersonator_user_id",
        ),
    )


__all__ = ["ImpersonationSession"]

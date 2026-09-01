"""User ORM model.

A **User** is a platform user of any ``role_type`` (``superadmin`` /
``agencyadmin`` / ``customeradmin``). See design "Table Details → users"
(Req 4.1, 4.3, 9.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from app.db.base import Base
from app.db.mixins import TimestampMixin

# Allowed role types (matches the DB CHECK constraint).
ROLE_TYPES = ("superadmin", "agencyadmin", "customeradmin")


class User(TimestampMixin, Base):
    """Platform user of any role_type.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``email`` — citext, unique, nullable (nullable for OTP-only accounts; at
      least one of email/mobile is required, enforced at the service layer).
      Unique index ``ux_users_email``.
    * ``mobile`` — varchar(20), unique, nullable. Unique index
      ``ux_users_mobile``.
    * ``password_hash`` — varchar(255), nullable (OTP-only users have none).
    * ``role_type`` — varchar(20), NOT NULL, CHECK IN
      (superadmin, agencyadmin, customeradmin).
    * ``agency_id`` — UUID FK → ``agencies.id``, nullable (set for
      ``agencyadmin``). Indexed as ``ix_users_agency_id``.
    * ``status`` — ``active`` / ``inactive`` / ``disabled`` / ``locked``;
      defaults to ``active``.
    * ``failed_login_count`` — int NOT NULL default 0.
    * ``locked_until`` — timestamptz, nullable.
    * ``created_at`` / ``updated_at`` — from :class:`TimestampMixin`.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_type: Mapped[str] = mapped_column(String(20), nullable=False)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agencies.id"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "role_type IN ('superadmin', 'agencyadmin', 'customeradmin')",
            name="ck_users_role_type",
        ),
        UniqueConstraint("email", name="ux_users_email"),
        UniqueConstraint("mobile", name="ux_users_mobile"),
        Index("ix_users_agency_id", "agency_id"),
    )


__all__ = ["User", "ROLE_TYPES"]

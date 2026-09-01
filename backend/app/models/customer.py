"""Customer ORM model.

A **Customer** is a Business onboarded by exactly one Agency. See design
"Table Details → customers" (Req 4.1, 4.3).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Customer(TimestampMixin, Base):
    """A Business onboarded by exactly one Agency.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``agency_id`` — UUID FK → ``agencies.id``, NOT NULL (each Customer
      belongs to exactly one Agency). Indexed as ``ix_customers_agency_id``.
    * ``name`` — display name, required, up to 200 chars.
    * ``status`` — ``active`` / ``suspended``; defaults to ``active``.
    * ``created_at`` / ``updated_at`` — from :class:`TimestampMixin`.
    """

    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agencies.id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )


__all__ = ["Customer"]

"""Agency ORM model.

An **Agency** is the top-level tenant that onboards Customers (Businesses) and
whose ``agencyadmin`` users are scoped to it. See design "Table Details →
agencies" (Req 4.1, 4.3).
"""

from __future__ import annotations

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Agency(TimestampMixin, Base):
    """One row per Agency.

    Columns
    -------
    * ``id`` — UUID primary key (generated application-side).
    * ``name`` — display name, required, up to 200 chars.
    * ``status`` — ``active`` / ``suspended``; defaults to ``active``.
    * ``created_at`` / ``updated_at`` — provided by :class:`TimestampMixin`.
    """

    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )


__all__ = ["Agency"]

"""CustomerUser association ORM model.

Maps a ``customeradmin`` user to one or more Customers (possibly across
different Agencies). See design "Table Details → customer_users"
(Req 4.5, 9.5).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CustomerUser(Base):
    """Association between a User (customeradmin) and a Customer.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``user_id`` — UUID FK → ``users.id``. Indexed.
    * ``customer_id`` — UUID FK → ``customers.id``. Indexed.

    A user may be assigned to many customers and a customer may have many
    assigned users, but each (user, customer) pair is unique.
    """

    __tablename__ = "customer_users"

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
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customers.id"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "customer_id", name="ux_customer_users_user_customer"),
        Index("ix_customer_users_user_id", "user_id"),
        Index("ix_customer_users_customer_id", "customer_id"),
    )


__all__ = ["CustomerUser"]

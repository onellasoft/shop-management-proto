"""CustomerSubscription ORM model.

A **CustomerSubscription** records a Customer's access to a single Module.
Access to a Module's SubModules, Resources, and Actions is gated by whether
that Customer has a *usable* subscription to the Module.

A subscription is **usable** when::

    status = 'active' AND (expires_at IS NULL OR expires_at > now())

(``expires_at`` NULL means "no expiry".) This is the invariant the
Authorization_Service ``is_module_usable`` check enforces (task 10.2).

See design "Table Details → customer_subscriptions" (Req 8.1):

* ``id`` PK
* ``customer_id`` FK → ``customers.id``
* ``module_id`` FK → ``modules.id``
* ``status`` varchar(20) NOT NULL default ``'active'``
* ``expires_at`` timestamptz nullable (null = no expiry)
* Unique(``customer_id``, ``module_id``)
* Index ``ix_subs_customer``
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CustomerSubscription(Base):
    """A Customer's subscription to a single Module (Req 8.1).

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``customer_id`` — UUID FK → ``customers.id``, NOT NULL.
    * ``module_id`` — UUID FK → ``modules.id``, NOT NULL.
    * ``status`` — varchar(20) NOT NULL, defaults to ``'active'``.
    * ``expires_at`` — timezone-aware timestamp, nullable. ``NULL`` means the
      subscription never expires.

    Constraints
    -----------
    * ``Unique(customer_id, module_id)`` — at most one subscription row per
      (Customer, Module) pair.
    * Index ``ix_subs_customer`` on ``customer_id`` for per-Customer lookups.
    """

    __tablename__ = "customer_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customers.id"),
        nullable=False,
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("modules.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "customer_id", "module_id", name="ux_customer_subscriptions_customer_module"
        ),
        Index("ix_subs_customer", "customer_id"),
    )


__all__ = ["CustomerSubscription"]

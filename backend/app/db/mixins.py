"""Reusable declarative mixins for Onella ORM models.

Two mixins are provided:

* :class:`TimestampMixin` — adds ``created_at`` / ``updated_at`` timestamptz
  columns populated by the database (``server_default now()``) with
  ``updated_at`` refreshed on every UPDATE.
* :class:`TenantMixin` — exposes nullable ``agency_id`` / ``customer_id`` UUID
  columns. These act as the hooks the tenant-filtering layer relies on:
  :func:`app.services...tenant_query` (design "Tenant Isolation" section)
  inspects ``customer_id`` / ``agency_id`` on a model to build the WHERE scope
  for every read and mutation. Models that are tenant-scoped inherit this mixin
  so the filter can be applied consistently (Req 9.2).

Both mixins use the SQLAlchemy 2.0 ``Mapped`` / ``mapped_column`` typed style.
They intentionally declare no ``__tablename__`` and are meant to be mixed into
concrete models that inherit :class:`app.db.base.Base`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP


class TimestampMixin:
    """Adds database-managed ``created_at`` and ``updated_at`` columns.

    * ``created_at`` — set once on INSERT via ``server_default now()``.
    * ``updated_at`` — set on INSERT and refreshed on every UPDATE. The
      database side uses ``server_default now()``; ``onupdate`` ensures the ORM
      also emits ``now()`` on UPDATE so the column tracks the latest mutation.

    Both columns are ``TIMESTAMP(timezone=True)`` (Postgres ``timestamptz``).
    """

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantMixin:
    """Exposes tenant-scope hooks used by the tenant-filtering layer.

    Provides nullable ``agency_id`` and ``customer_id`` UUID columns. The
    tenant query helper checks for the presence of these attributes on a model
    to decide how to scope reads/mutations:

    * a ``customer_id`` present → filter by the context's customer scope;
    * else an ``agency_id`` present → filter by the context's agency scope;
    * otherwise the query is fail-closed.

    Columns are nullable because a given tenant-scoped model may be scoped by
    only one of the two identifiers, and platform-level rows may carry neither.
    """

    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )


__all__ = ["TimestampMixin", "TenantMixin"]

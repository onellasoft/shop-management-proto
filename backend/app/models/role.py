"""Role, RolePermission, and UserRole ORM models.

Covers both the three **fixed system roles** (``superadmin`` /
``agencyadmin`` / ``customeradmin``) and **custom roles** scoped to a single
Customer, plus the association tables that grant Actions to Roles
(``role_permissions``) and assign Roles to Users (``user_roles``).

See design "Table Details → roles / role_permissions / user_roles"
(Req 4.1, 5.3, 7.2).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Role(Base):
    """A fixed system role or a Customer-scoped custom role.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``role_type`` — varchar(20), nullable. Set for the three fixed system
      roles (``superadmin`` / ``agencyadmin`` / ``customeradmin``); NULL for
      custom roles.
    * ``is_custom`` — boolean NOT NULL, default ``false``. The three fixed
      roles are seeded with ``is_custom=false``.
    * ``customer_id`` — UUID FK → ``customers.id``, nullable. Required when
      ``is_custom=true`` (custom roles are scoped to exactly one Customer,
      Req 7.2).
    * ``name`` — varchar(100), nullable. Set for custom roles (length 1–100
      when ``is_custom=true``).

    Constraints
    -----------
    * ``Unique(customer_id, name)`` — custom role names are unique within a
      Customer (Req 7.2).
    * When ``is_custom=true``: ``customer_id`` is NOT NULL and ``name`` length
      is 1–100.
    """

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    role_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_custom: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customers.id"),
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        UniqueConstraint("customer_id", "name", name="ux_roles_customer_name"),
        CheckConstraint(
            "(is_custom = false) OR "
            "(customer_id IS NOT NULL AND name IS NOT NULL "
            "AND char_length(name) BETWEEN 1 AND 100)",
            name="ck_roles_custom_requires_customer_and_name",
        ),
        Index("ix_roles_customer_id", "customer_id"),
    )


class RolePermission(Base):
    """Grants an Action to a Role (Req 5.3, 6.1).

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``role_id`` — UUID FK → ``roles.id``. Indexed.
    * ``action_id`` — UUID FK → ``actions.id``. Indexed.

    Each (role, action) pair is unique.
    """

    __tablename__ = "role_permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("roles.id"),
        nullable=False,
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("actions.id"),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("role_id", "action_id", name="ux_role_permissions_role_action"),
        Index("ix_role_permissions_role_id", "role_id"),
        Index("ix_role_permissions_action_id", "action_id"),
    )


class UserRole(Base):
    """Assigns a Role to a User, optionally scoped to a Customer.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``user_id`` — UUID FK → ``users.id``.
    * ``role_id`` — UUID FK → ``roles.id``.
    * ``customer_id`` — UUID FK → ``customers.id``, nullable (set for
      custom-role assignments scoped to a Customer).

    Each (user, role, customer) tuple is unique.
    """

    __tablename__ = "user_roles"

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
    role_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("roles.id"),
        nullable=False,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customers.id"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role_id",
            "customer_id",
            name="ux_user_roles_user_role_customer",
        ),
        Index("ix_user_roles_user_id", "user_id"),
        Index("ix_user_roles_role_id", "role_id"),
    )


__all__ = ["Role", "RolePermission", "UserRole"]

"""Permission graph ORM models.

The four-level permission model gates all access:

    Module → SubModule → Resource → Action

Every :class:`Action` carries an ``is_sensitive`` flag (default ``false``,
Req 13.1) and a denormalized, indexed ``action_key`` of the form
``module.submodule.resource.action`` for fast per-request lookup.

See design "Table Details → modules / submodules / resources / actions"
(Req 5.1, 5.2, 13.1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Module(Base):
    """Top level of the permission graph.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``key`` — globally unique machine key (e.g. ``"messaging"``).
    * ``name`` — human-readable display name.
    """

    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    submodules: Mapped[list["SubModule"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("key", name="ux_modules_key"),
    )


class SubModule(Base):
    """Second level; belongs to exactly one :class:`Module`.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``module_id`` — UUID FK → ``modules.id`` (not null).
    * ``key`` — machine key, unique within its module.
    * ``name`` — human-readable display name.
    """

    __tablename__ = "submodules"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("modules.id"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    module: Mapped["Module"] = relationship(back_populates="submodules")
    resources: Mapped[list["Resource"]] = relationship(
        back_populates="submodule",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("module_id", "key", name="ux_submodules_module_key"),
        Index("ix_submodules_module_id", "module_id"),
    )


class Resource(Base):
    """Third level; belongs to exactly one :class:`SubModule`.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``submodule_id`` — UUID FK → ``submodules.id`` (not null).
    * ``key`` — machine key, unique within its submodule.
    * ``name`` — human-readable display name.
    """

    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    submodule_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("submodules.id"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    submodule: Mapped["SubModule"] = relationship(back_populates="resources")
    actions: Mapped[list["Action"]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("submodule_id", "key", name="ux_resources_submodule_key"),
        Index("ix_resources_submodule_id", "submodule_id"),
    )


class Action(Base):
    """Leaf level; belongs to exactly one :class:`Resource`.

    Columns
    -------
    * ``id`` — UUID primary key.
    * ``resource_id`` — UUID FK → ``resources.id`` (not null).
    * ``name`` — action name (``create`` / ``read`` / ``update`` / ``delete``
      / custom), unique within its resource.
    * ``is_sensitive`` — boolean, not null, default ``false``. Sensitive
      actions are rejected during impersonation (Req 13.1, 13.2).
    * ``action_key`` — denormalized ``module.submodule.resource.action`` key,
      indexed for fast per-request permission lookup.
    """

    __tablename__ = "actions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resources.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    action_key: Mapped[str] = mapped_column(String(500), nullable=False)

    resource: Mapped["Resource"] = relationship(back_populates="actions")

    __table_args__ = (
        UniqueConstraint("resource_id", "name", name="ux_actions_resource_name"),
        Index("ix_actions_action_key", "action_key"),
    )


__all__ = ["Module", "SubModule", "Resource", "Action"]

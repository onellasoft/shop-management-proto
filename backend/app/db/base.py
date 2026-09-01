"""Declarative base for all SQLAlchemy ORM models.

All models in the Onella backend inherit from `Base`. Alembic's autogenerate
reads `Base.metadata` to detect schema changes.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. Provides a single ``metadata`` registry."""

    pass


__all__ = ["Base"]

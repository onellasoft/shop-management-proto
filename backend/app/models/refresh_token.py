"""RefreshToken ORM model.

Backs refresh-token **rotation** and **reuse-detection** (Req 3.5, 3.8, 3.9).

Each issued refresh token is persisted as one row. The row ``id`` doubles as
the token's ``jti`` (JWT ID). Tokens issued from a single login form a
**family** sharing one ``family_id``; on every refresh the presented token is
marked ``used`` and a new row is minted with ``rotated_from`` pointing back at
it. Presenting an already-``used`` (or ``revoked``) token is treated as reuse
and the whole family is revoked.

See design "Table Details → refresh_tokens":

* ``id``           — UUID PK (also the token's ``jti``).
* ``user_id``      — UUID FK → ``users.id``; owner of the token.
* ``family_id``    — UUID NOT NULL; the issuance chain a token belongs to.
* ``rotated_from`` — UUID FK → ``refresh_tokens.id``, nullable; the token this
  one was rotated from (NULL for the first token in a family).
* ``token_hash``   — varchar(255) NOT NULL; SHA-256 hash of the token value
  (the raw token is never stored).
* ``used``         — boolean NOT NULL default ``false``; set true on rotation.
* ``revoked``      — boolean NOT NULL default ``false``; set true on logout or
  family-wide reuse revocation.
* ``expires_at``   — timestamptz NOT NULL.
* ``created_at``   — from :class:`TimestampMixin`.

Indexes: ``ix_rt_family`` (``family_id``), ``ix_rt_user`` (``user_id``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import TIMESTAMP

from app.db.base import Base
from app.db.mixins import TimestampMixin


class RefreshToken(TimestampMixin, Base):
    """A persisted refresh token supporting rotation and reuse-detection."""

    __tablename__ = "refresh_tokens"

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
    family_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )
    rotated_from: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id"),
        nullable=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_rt_family", "family_id"),
        Index("ix_rt_user", "user_id"),
    )


__all__ = ["RefreshToken"]

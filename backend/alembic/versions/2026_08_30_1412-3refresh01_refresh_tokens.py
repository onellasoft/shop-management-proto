"""refresh tokens

Revision ID: 3refresh01
Revises: 2fabperm01
Create Date: 2026-08-30 14:12:00.000000+00:00

Creates the ``refresh_tokens`` table backing refresh-token rotation and
reuse-detection (task 6.1; design "Table Details → refresh_tokens";
Req 3.5, 3.8, 3.9).

Columns:
* ``id``           — UUID PK (also the token's ``jti``).
* ``user_id``      — UUID FK → ``users.id``.
* ``family_id``    — UUID NOT NULL (issuance chain).
* ``rotated_from`` — UUID FK → ``refresh_tokens.id``, nullable.
* ``token_hash``   — varchar(255) NOT NULL (SHA-256 of the token value).
* ``used``         — boolean NOT NULL default false.
* ``revoked``      — boolean NOT NULL default false.
* ``expires_at``   — timestamptz NOT NULL.
* ``created_at``   — timestamptz NOT NULL (TimestampMixin).
* ``updated_at``   — timestamptz NOT NULL (TimestampMixin).

Indexes: ``ix_rt_family`` (family_id), ``ix_rt_user`` (user_id).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3refresh01'
down_revision: str | None = '2fabperm01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "rotated_from", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "used", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "revoked", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "expires_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rotated_from"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_rotated_from_refresh_tokens"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
    )
    op.create_index("ix_rt_family", "refresh_tokens", ["family_id"])
    op.create_index("ix_rt_user", "refresh_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_rt_user", table_name="refresh_tokens")
    op.drop_index("ix_rt_family", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

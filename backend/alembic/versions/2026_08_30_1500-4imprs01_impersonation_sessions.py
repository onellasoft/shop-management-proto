"""impersonation sessions

Revision ID: 4imprs01
Revises: 3fabsubs01
Create Date: 2026-08-30 15:00:00.000000+00:00

Creates the ``impersonation_sessions`` table backing the impersonation session
lifecycle (task 17.1; design "Table Details → impersonation_sessions";
Req 11.4, 11.6).

Columns:
* ``id``                       — UUID PK.
* ``impersonator_user_id``     — UUID FK → ``users.id``, NOT NULL.
* ``impersonated_agency_id``   — UUID FK → ``agencies.id``, nullable.
* ``impersonated_customer_id`` — UUID FK → ``customers.id``, nullable.
* ``active``                   — boolean NOT NULL default true.
* ``started_at``               — timestamptz NOT NULL default now().
* ``ended_at``                 — timestamptz nullable.
* ``created_at``               — timestamptz NOT NULL (TimestampMixin).
* ``updated_at``               — timestamptz NOT NULL (TimestampMixin).

Constraints / indexes:
* ``ck_impersonation_sessions_one_target`` — CHECK exactly one of
  agency/customer target is set (XOR).
* ``uq_impersonation_active_per_impersonator`` — partial UNIQUE index over
  ``impersonator_user_id`` WHERE ``active`` (at most one active session per
  impersonator, Req 11.6).
* ``ix_impersonation_sessions_impersonator`` — index on
  ``impersonator_user_id``.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4imprs01'
down_revision: str | None = '3fabsubs01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "impersonation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "impersonator_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "impersonated_agency_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "impersonated_customer_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "active", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "ended_at", sa.TIMESTAMP(timezone=True), nullable=True
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
        sa.CheckConstraint(
            "(impersonated_agency_id IS NOT NULL) "
            "<> (impersonated_customer_id IS NOT NULL)",
            name="ck_impersonation_sessions_one_target",
        ),
        sa.ForeignKeyConstraint(
            ["impersonator_user_id"],
            ["users.id"],
            name=op.f(
                "fk_impersonation_sessions_impersonator_user_id_users"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["impersonated_agency_id"],
            ["agencies.id"],
            name=op.f(
                "fk_impersonation_sessions_impersonated_agency_id_agencies"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["impersonated_customer_id"],
            ["customers.id"],
            name=op.f(
                "fk_impersonation_sessions_impersonated_customer_id_customers"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_impersonation_sessions")
        ),
    )
    op.create_index(
        "ix_impersonation_sessions_impersonator",
        "impersonation_sessions",
        ["impersonator_user_id"],
    )
    op.create_index(
        "uq_impersonation_active_per_impersonator",
        "impersonation_sessions",
        ["impersonator_user_id"],
        unique=True,
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_impersonation_active_per_impersonator",
        table_name="impersonation_sessions",
    )
    op.drop_index(
        "ix_impersonation_sessions_impersonator",
        table_name="impersonation_sessions",
    )
    op.drop_table("impersonation_sessions")

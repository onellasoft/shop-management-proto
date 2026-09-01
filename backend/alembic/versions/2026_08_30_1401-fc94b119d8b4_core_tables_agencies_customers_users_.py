"""core tables agencies customers users customer_users

Revision ID: fc94b119d8b4
Revises:
Create Date: 2026-08-30 14:01:41.617106+00:00

Initial migration creating the four core tenancy/user tables:

* ``agencies``       — top-level tenant (Req 4.1, 4.3)
* ``customers``      — Business onboarded by exactly one Agency (Req 4.1, 4.3)
* ``users``          — platform users of any role_type (Req 4.1, 4.3, 9.5)
* ``customer_users`` — customeradmin ↔ customer assignment (Req 4.5, 9.5)

This migration is intentionally scoped to ONLY these four core tables so it
stays independent of the permission/role graph introduced in later tasks
(8.1/8.2).

``users.email`` uses the PostgreSQL ``CITEXT`` type, which requires the
``citext`` extension. The upgrade therefore issues
``CREATE EXTENSION IF NOT EXISTS citext`` before creating the ``users`` table.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fc94b119d8b4'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``users.email`` is CITEXT; ensure the extension exists first.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    # --- agencies -----------------------------------------------------------
    op.create_table(
        "agencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agencies")),
    )

    # --- customers ----------------------------------------------------------
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
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
            ["agency_id"],
            ["agencies.id"],
            name=op.f("fk_customers_agency_id_agencies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
    )
    op.create_index("ix_customers_agency_id", "customers", ["agency_id"])

    # --- users --------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("mobile", sa.String(length=20), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role_type", sa.String(length=20), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "locked_until",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
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
            "role_type IN ('superadmin', 'agencyadmin', 'customeradmin')",
            name="ck_users_role_type",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            name=op.f("fk_users_agency_id_agencies"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name="ux_users_email"),
        sa.UniqueConstraint("mobile", name="ux_users_mobile"),
    )
    op.create_index("ix_users_agency_id", "users", ["agency_id"])

    # --- customer_users -----------------------------------------------------
    op.create_table(
        "customer_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_users_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_customer_users_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_users")),
        sa.UniqueConstraint(
            "user_id",
            "customer_id",
            name="ux_customer_users_user_customer",
        ),
    )
    op.create_index(
        "ix_customer_users_user_id", "customer_users", ["user_id"]
    )
    op.create_index(
        "ix_customer_users_customer_id", "customer_users", ["customer_id"]
    )


def downgrade() -> None:
    # Drop in reverse dependency order: customer_users → users → customers →
    # agencies. Indexes are dropped implicitly with their tables.
    op.drop_index("ix_customer_users_customer_id", table_name="customer_users")
    op.drop_index("ix_customer_users_user_id", table_name="customer_users")
    op.drop_table("customer_users")

    op.drop_index("ix_users_agency_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_customers_agency_id", table_name="customers")
    op.drop_table("customers")

    op.drop_table("agencies")

    # Optionally drop the citext extension. Kept conservative: only drop if no
    # other object depends on it. Using RESTRICT avoids cascading surprises.
    op.execute("DROP EXTENSION IF EXISTS citext RESTRICT")

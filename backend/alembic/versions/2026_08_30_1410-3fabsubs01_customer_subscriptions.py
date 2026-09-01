"""customer_subscriptions

Revision ID: 3fabsubs01
Revises: 3refresh01
Create Date: 2026-08-30 14:14:00.000000+00:00

Creates the ``customer_subscriptions`` table (task 10.1), which records a
Customer's access to a single Module. Module gating (task 10.2) treats a
subscription as *usable* when::

    status = 'active' AND (expires_at IS NULL OR expires_at > now())

Table (design "Table Details → customer_subscriptions", Req 8.1):
* ``id`` PK
* ``customer_id`` FK → ``customers.id``
* ``module_id`` FK → ``modules.id``
* ``status`` varchar(20) NOT NULL default ``'active'``
* ``expires_at`` timestamptz nullable (null = no expiry)
* Unique(``customer_id``, ``module_id``)
* Index ``ix_subs_customer`` on ``customer_id``

Chaining note (concurrent task 6.1)
-----------------------------------
Task 6.1 (refresh_tokens) added its migration ``3refresh01`` concurrently,
also chained off the permission-graph head ``2fabperm01``. That produced two
heads. Since there is no data dependency between refresh tokens and customer
subscriptions, this migration resolves the branch by chaining *after*
``3refresh01`` (``2fabperm01 -> 3refresh01 -> 3fabsubs01``), keeping a single
linear history. The FK this migration needs (``modules``) is created by
``2fabperm01``, which precedes ``3refresh01`` in the chain, so ordering is
valid.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "3fabsubs01"
down_revision: str | None = "3refresh01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_subscriptions_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_customer_subscriptions_module_id_modules"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_subscriptions")),
        sa.UniqueConstraint(
            "customer_id",
            "module_id",
            name="ux_customer_subscriptions_customer_module",
        ),
    )
    op.create_index(
        "ix_subs_customer", "customer_subscriptions", ["customer_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_subs_customer", table_name="customer_subscriptions")
    op.drop_table("customer_subscriptions")

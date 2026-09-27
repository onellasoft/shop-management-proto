"""audit_logs and audit_failures

Revision ID: 5audit01
Revises: 4imprs01
Create Date: 2026-08-30 15:10:00.000000+00:00

Creates the ``audit_logs`` and ``audit_failures`` tables backing mutation audit
logging (task 20.2; design "Table Details → audit_logs" / "audit_failures";
Req 14.1, 14.3, 14.4, 14.6, 14.7), and installs a PostgreSQL trigger enforcing
the **append-only** invariant on ``audit_logs`` at the DB level (Req 14.6).

audit_logs columns:
* ``id``                   — UUID PK.
* ``user_id``              — UUID FK → ``users.id`` (the actor), NOT NULL.
* ``role_type``            — varchar(20) nullable.
* ``agency_id``            — UUID nullable; plain indexed UUID, NOT an FK
  (audit retention is decoupled from the tenant row lifecycle).
* ``customer_id``          — UUID nullable; plain indexed UUID, NOT an FK.
* ``module`` / ``sub_module`` / ``resource`` / ``action`` — varchar nullable.
* ``old_value`` / ``new_value`` — jsonb nullable (before/after diff).
* ``impersonation``        — boolean NOT NULL default false.
* ``impersonator_user_id`` — UUID nullable.
* ``created_at``           — timestamptz NOT NULL default now().

The table has NO ``updated_at``: it is append-only (Req 14.6).

Indexes: ``ix_audit_created_at`` (created_at DESC), ``ix_audit_agency``,
``ix_audit_customer``, ``ix_audit_user``, ``ix_audit_action``.

Append-only trigger (Req 14.6):
* ``audit_logs_reject_mutation()`` — a plpgsql trigger function that RAISEs an
  exception for any UPDATE or DELETE.
* ``trg_audit_logs_append_only`` — a BEFORE UPDATE OR DELETE row-level trigger
  invoking that function, so the table rejects updates/deletes at the DB level.

audit_failures columns:
* ``id``         — UUID PK.
* ``payload``    — jsonb nullable (the unrecorded AuditEntry).
* ``error``      — text nullable.
* ``created_at`` — timestamptz NOT NULL default now().
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5audit01'
down_revision: str | None = '4imprs01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_type", sa.String(length=20), nullable=True),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module", sa.String(length=100), nullable=True),
        sa.Column("sub_module", sa.String(length=100), nullable=True),
        sa.Column("resource", sa.String(length=100), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=True),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "impersonation",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column(
            "impersonator_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    # created_at DESC so newest-first audit queries can use the index (Req 15.5).
    op.create_index(
        "ix_audit_created_at",
        "audit_logs",
        ["created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index("ix_audit_agency", "audit_logs", ["agency_id"])
    op.create_index("ix_audit_customer", "audit_logs", ["customer_id"])
    op.create_index("ix_audit_user", "audit_logs", ["user_id"])
    op.create_index("ix_audit_action", "audit_logs", ["action"])

    op.create_table(
        "audit_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_failures")),
    )

    # Append-only enforcement at the DB level (Req 14.6): reject UPDATE/DELETE
    # on audit_logs. A BEFORE trigger raising an exception prevents the row
    # from ever being modified or removed.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_logs_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_logs is append-only: % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_reject_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_append_only ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_reject_mutation();")

    op.drop_table("audit_failures")

    op.drop_index("ix_audit_action", table_name="audit_logs")
    op.drop_index("ix_audit_user", table_name="audit_logs")
    op.drop_index("ix_audit_customer", table_name="audit_logs")
    op.drop_index("ix_audit_agency", table_name="audit_logs")
    op.drop_index("ix_audit_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")

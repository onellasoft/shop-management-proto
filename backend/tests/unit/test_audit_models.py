"""Unit tests for the AuditLog and AuditFailure models (Task 20.2).

Verify the ORM schema definitions match the design "Table Details →
audit_logs" / "audit_failures" at the metadata level (no live DB): column
presence / nullability / types, defaults, the five audit_logs indexes, the
user_id FK, that audit_logs is append-only (only ``created_at`` — no
``updated_at``), and registration on ``Base.metadata`` / ``app.models.__all__``
(Req 14.1, 14.3, 14.4, 14.6, 14.7).

The DB-level append-only trigger cannot be exercised here without a live
database; its presence is covered by the migration plus the append-only
property test (Task 21.4) / integration test (Task 23.1).
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import TIMESTAMP

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.models import AuditFailure, AuditLog


def _cols(table):
    return {c.name: c for c in table.columns}


def test_models_registered_on_metadata_and_exports():
    assert "audit_logs" in Base.metadata.tables
    assert "audit_failures" in Base.metadata.tables
    assert "AuditLog" in app.models.__all__
    assert "AuditFailure" in app.models.__all__


def test_audit_logs_table_name_and_columns():
    t = AuditLog.__table__
    assert t.name == "audit_logs"
    cols = _cols(t)
    expected = {
        "id",
        "user_id",
        "role_type",
        "agency_id",
        "customer_id",
        "module",
        "sub_module",
        "resource",
        "action",
        "old_value",
        "new_value",
        "impersonation",
        "impersonator_user_id",
        "created_at",
    }
    assert expected == set(cols)


def test_audit_logs_is_append_only_no_updated_at():
    # Append-only (Req 14.6): the table tracks only when a row was created;
    # there is no updated_at (it must never be mutated).
    cols = _cols(AuditLog.__table__)
    assert "created_at" in cols
    assert "updated_at" not in cols


def test_audit_logs_nullability_and_defaults():
    cols = _cols(AuditLog.__table__)
    assert cols["id"].primary_key
    # actor is required
    assert not cols["user_id"].nullable
    # tenant identifiers and permission-graph names are nullable
    assert cols["role_type"].nullable
    assert cols["agency_id"].nullable
    assert cols["customer_id"].nullable
    assert cols["module"].nullable
    assert cols["sub_module"].nullable
    assert cols["resource"].nullable
    assert cols["action"].nullable
    # diff values
    assert cols["old_value"].nullable
    assert cols["new_value"].nullable
    # impersonation flag: not null, defaults to false (Req 14.4)
    assert not cols["impersonation"].nullable
    assert cols["impersonation"].server_default.arg == "false"
    assert cols["impersonator_user_id"].nullable
    # created_at: not null with a server default
    assert not cols["created_at"].nullable
    assert cols["created_at"].server_default is not None


def test_audit_logs_column_types():
    cols = _cols(AuditLog.__table__)
    assert isinstance(cols["old_value"].type, JSONB)
    assert isinstance(cols["new_value"].type, JSONB)
    assert isinstance(cols["impersonation"].type, Boolean)
    assert isinstance(cols["role_type"].type, String)
    assert isinstance(cols["created_at"].type, TIMESTAMP)
    assert cols["created_at"].type.timezone is True


def test_audit_logs_user_fk_but_tenant_ids_are_plain():
    cols = _cols(AuditLog.__table__)
    # user_id references users.id (the actor)
    assert any(
        fk.column.table.name == "users" for fk in cols["user_id"].foreign_keys
    )
    # agency_id / customer_id are deliberately NOT foreign keys (design: plain
    # uuid on AUDIT_LOGS; decouples audit retention from tenant row lifecycle).
    assert not cols["agency_id"].foreign_keys
    assert not cols["customer_id"].foreign_keys


def test_audit_logs_indexes():
    index_names = {i.name for i in AuditLog.__table__.indexes}
    assert {
        "ix_audit_created_at",
        "ix_audit_agency",
        "ix_audit_customer",
        "ix_audit_user",
        "ix_audit_action",
    } == index_names


def test_audit_failures_table_name_and_columns():
    t = AuditFailure.__table__
    assert t.name == "audit_failures"
    cols = _cols(t)
    assert set(cols) == {"id", "payload", "error", "created_at"}
    assert cols["id"].primary_key
    assert isinstance(cols["payload"].type, JSONB)
    assert isinstance(cols["error"].type, Text)
    assert not cols["created_at"].nullable
    assert cols["created_at"].server_default is not None

"""Unit tests for the ImpersonationSession model (Task 17.1).

Verify the ORM schema definition matches the design "Table Details →
impersonation_sessions" at the metadata level (no live DB): column presence /
nullability, FK targets, the XOR CHECK on the impersonation target, the partial
unique index enforcing one active session per impersonator, and registration on
``Base.metadata`` / ``app.models.__all__`` (Req 11.4, 11.6).
"""

from __future__ import annotations

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.models import ImpersonationSession


def _cols(table):
    return {c.name: c for c in table.columns}


def test_model_registered_on_metadata_and_exports():
    assert "impersonation_sessions" in Base.metadata.tables
    assert "ImpersonationSession" in app.models.__all__


def test_table_name_and_columns():
    t = ImpersonationSession.__table__
    assert t.name == "impersonation_sessions"
    cols = _cols(t)
    expected = {
        "id",
        "impersonator_user_id",
        "impersonated_agency_id",
        "impersonated_customer_id",
        "active",
        "started_at",
        "ended_at",
        "created_at",
        "updated_at",
    }
    assert expected <= set(cols)


def test_column_nullability_and_defaults():
    cols = _cols(ImpersonationSession.__table__)
    assert cols["id"].primary_key
    # impersonator is required; both impersonated targets are individually
    # nullable (the XOR CHECK enforces exactly one at the row level).
    assert not cols["impersonator_user_id"].nullable
    assert cols["impersonated_agency_id"].nullable
    assert cols["impersonated_customer_id"].nullable
    # active defaults to true, not null
    assert not cols["active"].nullable
    assert cols["active"].server_default.arg == "true"
    # started_at not null with server default; ended_at nullable
    assert not cols["started_at"].nullable
    assert cols["started_at"].server_default is not None
    assert cols["ended_at"].nullable


def test_foreign_key_targets():
    cols = _cols(ImpersonationSession.__table__)
    assert any(
        fk.column.table.name == "users"
        for fk in cols["impersonator_user_id"].foreign_keys
    )
    assert any(
        fk.column.table.name == "agencies"
        for fk in cols["impersonated_agency_id"].foreign_keys
    )
    assert any(
        fk.column.table.name == "customers"
        for fk in cols["impersonated_customer_id"].foreign_keys
    )


def test_xor_check_constraint_on_target():
    t = ImpersonationSession.__table__
    check = next(
        c
        for c in t.constraints
        if getattr(c, "name", None) == "ck_impersonation_sessions_one_target"
    )
    sqltext = str(check.sqltext)
    # XOR semantics: exactly one of the two impersonated_* columns is non-null.
    assert "impersonated_agency_id" in sqltext
    assert "impersonated_customer_id" in sqltext
    assert "<>" in sqltext


def test_partial_unique_index_one_active_per_impersonator():
    t = ImpersonationSession.__table__
    idx = next(
        i
        for i in t.indexes
        if i.name == "uq_impersonation_active_per_impersonator"
    )
    assert idx.unique
    assert {c.name for c in idx.columns} == {"impersonator_user_id"}
    # Partial index: WHERE active.
    where = idx.dialect_options["postgresql"].get("where")
    assert where is not None
    assert "active" in str(where)


def test_lookup_index_on_impersonator():
    t = ImpersonationSession.__table__
    assert "ix_impersonation_sessions_impersonator" in {
        i.name for i in t.indexes
    }

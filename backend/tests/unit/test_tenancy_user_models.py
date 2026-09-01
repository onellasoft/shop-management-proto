"""Unit tests for core tenancy and user models (Task 2.1).

Verify the ORM schema definitions match the design "Table Details" section:
column presence/nullability, defaults, indexes, unique constraints, the
role_type CHECK, and that every model registers on ``Base.metadata`` so
Alembic autogenerate can see them (Req 4.1, 4.3, 4.5, 9.5).
"""

from __future__ import annotations

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.models import Agency, Customer, CustomerUser, User
from app.models.user import ROLE_TYPES


def _cols(table):
    return {c.name: c for c in table.columns}


def test_all_models_registered_on_metadata():
    tables = set(Base.metadata.tables.keys())
    assert {"agencies", "customers", "users", "customer_users"} <= tables


def test_agency_schema():
    t = Agency.__table__
    cols = _cols(t)
    assert cols["id"].primary_key
    assert not cols["name"].nullable
    assert not cols["status"].nullable
    assert cols["status"].server_default.arg == "active"
    assert "created_at" in cols and "updated_at" in cols


def test_customer_schema_and_index():
    t = Customer.__table__
    cols = _cols(t)
    assert cols["id"].primary_key
    # agency_id FK is NOT NULL
    assert not cols["agency_id"].nullable
    assert any(fk.column.table.name == "agencies" for fk in cols["agency_id"].foreign_keys)
    assert cols["status"].server_default.arg == "active"
    assert "ix_customers_agency_id" in {i.name for i in t.indexes}


def test_user_schema_constraints_and_indexes():
    t = User.__table__
    cols = _cols(t)
    assert cols["id"].primary_key
    # email/mobile/password_hash nullable
    assert cols["email"].nullable
    assert cols["mobile"].nullable
    assert cols["password_hash"].nullable
    # role_type not null
    assert not cols["role_type"].nullable
    # agency_id FK nullable
    assert cols["agency_id"].nullable
    assert any(fk.column.table.name == "agencies" for fk in cols["agency_id"].foreign_keys)
    # defaults
    assert cols["status"].server_default.arg == "active"
    assert cols["failed_login_count"].server_default.arg == "0"
    assert not cols["failed_login_count"].nullable
    assert cols["locked_until"].nullable
    # unique constraints + index names
    constraint_names = {c.name for c in t.constraints}
    assert {"ux_users_email", "ux_users_mobile", "ck_users_role_type"} <= constraint_names
    assert "ix_users_agency_id" in {i.name for i in t.indexes}


def test_user_role_type_check_covers_expected_values():
    assert ROLE_TYPES == ("superadmin", "agencyadmin", "customeradmin")
    check = next(
        c for c in User.__table__.constraints if getattr(c, "name", None) == "ck_users_role_type"
    )
    sqltext = str(check.sqltext)
    for role in ROLE_TYPES:
        assert role in sqltext


def test_customer_user_unique_and_indexes():
    t = CustomerUser.__table__
    cols = _cols(t)
    assert cols["id"].primary_key
    assert any(fk.column.table.name == "users" for fk in cols["user_id"].foreign_keys)
    assert any(fk.column.table.name == "customers" for fk in cols["customer_id"].foreign_keys)
    # unique on (user_id, customer_id)
    uniques = [c for c in t.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({col.name for col in u.columns} == {"user_id", "customer_id"} for u in uniques)
    index_names = {i.name for i in t.indexes}
    assert {"ix_customer_users_user_id", "ix_customer_users_customer_id"} <= index_names

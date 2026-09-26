"""Unit tests for the application-level tenant filtering helpers (Task 14.1).

Covers :func:`app.db.tenant_query.tenant_query` and
:func:`app.db.tenant_query.verify_tenant_scope` against the design's tenant
isolation rules (Req 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 4.4).

The generated WHERE clauses are asserted by compiling the statement to SQL
(``str(stmt)`` / literal-binding), so no live database is required.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.errors import TenantBoundaryViolationError
from app.core.tenant_context import TenantContext
from app.db.mixins import TenantMixin
from app.db.tenant_query import tenant_query, verify_tenant_scope


# ---------------------------------------------------------------------------
# Lightweight test models on an isolated metadata (no Base.metadata pollution).
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class CustomerScoped(TenantMixin, _TestBase):
    """A model carrying both tenant columns; customer_id takes precedence."""

    __tablename__ = "cq_customer_scoped"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class AgencyScoped(_TestBase):
    """A model carrying only an agency_id column (no customer_id)."""

    __tablename__ = "cq_agency_scoped"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class NoTenant(_TestBase):
    """A model with neither tenant column — must fail closed."""

    __tablename__ = "cq_no_tenant"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# TenantContext factories.
# ---------------------------------------------------------------------------


def _ctx(
    *,
    role_type: str,
    agency_scope: uuid.UUID | None,
    customer_scope: frozenset[uuid.UUID],
    is_superadmin: bool,
) -> TenantContext:
    return TenantContext(
        user_id=uuid.uuid4(),
        role_type=role_type,
        agency_scope=agency_scope,
        customer_scope=customer_scope,
        is_superadmin=is_superadmin,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _superadmin() -> TenantContext:
    return _ctx(
        role_type="superadmin",
        agency_scope=None,
        customer_scope=frozenset(),
        is_superadmin=True,
    )


def _customeradmin(customer_ids: frozenset[uuid.UUID]) -> TenantContext:
    return _ctx(
        role_type="customeradmin",
        agency_scope=None,
        customer_scope=customer_ids,
        is_superadmin=False,
    )


def _agencyadmin(agency_id: uuid.UUID) -> TenantContext:
    return _ctx(
        role_type="agencyadmin",
        agency_scope=agency_id,
        customer_scope=frozenset(),
        is_superadmin=False,
    )


def _compiled(stmt) -> str:
    """Compile a statement to a SQL string with literal-bound parameters."""
    return str(
        stmt.compile(compile_kwargs={"literal_binds": True})
    )


# ---------------------------------------------------------------------------
# tenant_query
# ---------------------------------------------------------------------------


def test_superadmin_query_is_unfiltered():
    """Req 9.3 — superadmin gets no tenant WHERE clause."""
    stmt = tenant_query(CustomerScoped, _superadmin())
    assert stmt.whereclause is None
    assert "WHERE" not in _compiled(stmt).upper()


def test_customer_scoped_model_filters_by_customer_id_in_scope():
    """Req 9.4/9.5/9.6 — customer_id IN scope."""
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    ctx = _customeradmin(frozenset({c1, c2}))
    stmt = tenant_query(CustomerScoped, ctx)

    assert stmt.whereclause is not None
    sql = _compiled(stmt)
    assert "customer_id IN" in sql
    # PG_UUID literal binds render without hyphens; match on .hex.
    assert c1.hex in sql and c2.hex in sql


def test_customer_scope_empty_non_superadmin_matches_nothing():
    """Empty customer_scope for a non-superadmin must be IN () (zero rows),
    never collapsed into no-filter (fail-closed)."""
    ctx = _customeradmin(frozenset())
    stmt = tenant_query(CustomerScoped, ctx)

    # There is still a WHERE clause (not unfiltered).
    assert stmt.whereclause is not None
    sql = _compiled(stmt).upper()
    assert "CUSTOMER_ID IN" in sql
    # No customer id literals leak in; the IN set is empty.
    # SQLAlchemy renders an empty IN as a contradiction that matches no rows.
    assert "WHERE" in sql


def test_agency_scoped_model_filters_by_agency_id_equals():
    """Model with agency_id but no customer_id → agency_id == scope."""
    agency = uuid.uuid4()
    ctx = _agencyadmin(agency)
    stmt = tenant_query(AgencyScoped, ctx)

    assert stmt.whereclause is not None
    sql = _compiled(stmt)
    assert "agency_id =" in sql
    assert agency.hex in sql


def test_agency_scoped_model_without_agency_scope_fails_closed():
    """A non-superadmin lacking an agency scope must not leak agency rows."""
    ctx = _customeradmin(frozenset())  # agency_scope is None
    stmt = tenant_query(AgencyScoped, ctx)

    assert stmt.whereclause is not None
    # Fail-closed: matches nothing rather than the whole table.
    sql = _compiled(stmt).lower()
    assert "false" in sql


def test_model_without_tenant_columns_fails_closed():
    """Req 9.7 — a model with neither tenant column matches nothing."""
    ctx = _customeradmin(frozenset({uuid.uuid4()}))
    stmt = tenant_query(NoTenant, ctx)

    assert stmt.whereclause is not None
    sql = _compiled(stmt).lower()
    assert "false" in sql


def test_customer_id_precedence_over_agency_id():
    """When both columns exist, customer_id scoping wins (per design order)."""
    c1 = uuid.uuid4()
    ctx = _ctx(
        role_type="agencyadmin",
        agency_scope=uuid.uuid4(),
        customer_scope=frozenset({c1}),
        is_superadmin=False,
    )
    stmt = tenant_query(CustomerScoped, ctx)
    sql = _compiled(stmt)
    assert "customer_id IN" in sql
    assert "agency_id =" not in sql


# ---------------------------------------------------------------------------
# verify_tenant_scope
# ---------------------------------------------------------------------------


def test_verify_superadmin_passes_for_any_row():
    """Superadmin always passes re-verification (Req 4.2/9.3)."""
    verify_tenant_scope(
        ctx=_superadmin(),
        agency_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
    )  # no exception


def test_verify_customer_in_scope_passes():
    c1 = uuid.uuid4()
    verify_tenant_scope(ctx=_customeradmin(frozenset({c1})), customer_id=c1)


def test_verify_customer_out_of_scope_raises():
    in_scope = uuid.uuid4()
    out_of_scope = uuid.uuid4()
    with pytest.raises(TenantBoundaryViolationError):
        verify_tenant_scope(
            ctx=_customeradmin(frozenset({in_scope})),
            customer_id=out_of_scope,
        )


def test_verify_customer_empty_scope_raises():
    with pytest.raises(TenantBoundaryViolationError):
        verify_tenant_scope(
            ctx=_customeradmin(frozenset()),
            customer_id=uuid.uuid4(),
        )


def test_verify_agency_in_scope_passes():
    agency = uuid.uuid4()
    verify_tenant_scope(ctx=_agencyadmin(agency), agency_id=agency)


def test_verify_agency_out_of_scope_raises():
    with pytest.raises(TenantBoundaryViolationError):
        verify_tenant_scope(ctx=_agencyadmin(uuid.uuid4()), agency_id=uuid.uuid4())


def test_verify_no_identifier_non_superadmin_fails_closed():
    """Req 9.7 — no tenant identifier for a non-superadmin fails closed."""
    with pytest.raises(TenantBoundaryViolationError):
        verify_tenant_scope(ctx=_customeradmin(frozenset({uuid.uuid4()})))


def test_verify_customer_takes_precedence_over_agency():
    """When both are provided, customer_id is checked first."""
    c1 = uuid.uuid4()
    # customer in scope but agency mismatched → still passes on customer.
    verify_tenant_scope(
        ctx=_customeradmin(frozenset({c1})),
        customer_id=c1,
        agency_id=uuid.uuid4(),
    )

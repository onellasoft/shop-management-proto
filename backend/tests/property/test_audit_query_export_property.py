"""Property-based tests for audit query/export (Task 22.4 — Req 15.1-15.6).

# Feature: onella-backend, Property 30: Audit query isolation, filtering, ordering, and pagination

**Validates: Requirements 15.1, 15.2, 15.3, 15.4, 15.5**

# Feature: onella-backend, Property 31: Audit export format and cap

**Validates: Requirements 15.6**

Both tests drive the REAL ``AuditService.query`` / ``AuditService.export`` over
Hypothesis-generated worlds using the same in-memory fake session approach as
``tests/unit/test_audit_service_query.py`` — the fake genuinely evaluates
compiled WHERE clauses, applies desc ordering, and honours offset/limit so
isolation, filtering, and ordering are exercised end to end.

No live database is required.  Because the service methods are async the test
bodies call ``asyncio.run`` per example, mirroring the other property tests.
"""

from __future__ import annotations

import asyncio
import csv
import datetime
import io
import json
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.sql import operators

from app.core.errors import InvalidDateRangeError
from app.core.tenant_context import TenantContext
from app.models.audit import AuditLog
from app.services.audit_service import (
    DEFAULT_PAGE_SIZE,
    EXPORT_MAX_RECORDS,
    MAX_PAGE_SIZE,
    AuditFilter,
    AuditService,
)

UTC = datetime.timezone.utc

# ---------------------------------------------------------------------------
# In-memory fake AsyncSession — reused from test_audit_service_query.py style
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows
    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, *, scalar_rows=None, scalar_value=None):
        self._scalar_rows = scalar_rows
        self._scalar_value = scalar_value
    def scalars(self):
        return _ScalarResult(self._scalar_rows or [])
    def scalar_one(self):
        return self._scalar_value


class _FakeSession:
    """Filters/orders/paginates AuditLog rows in Python against compiled SQL."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.last_limit = None  # records the LIMIT the service set (for cap assertion)

    async def execute(self, statement):
        if self._is_count(statement):
            subq = statement.get_final_froms()[0]
            matched = self._filter(subq.element)
            return _Result(scalar_value=len(matched))
        matched = self._filter(statement)
        matched = self._order_offset_limit(statement, matched)
        return _Result(scalar_rows=matched)

    @staticmethod
    def _is_count(statement):
        d = statement.column_descriptions
        return not d or d[0].get("entity") is not AuditLog

    def _filter(self, statement):
        w = statement.whereclause
        return [r for r in self.rows if self._matches(w, r)]

    @staticmethod
    def _matches(whereclause, row):
        if whereclause is None:
            return True
        return _FakeSession._eval(whereclause, row)

    @staticmethod
    def _eval(clause, row):
        if clause.__class__.__name__ == "False_":
            return False
        if clause.__class__.__name__ == "AsBoolean":
            return _FakeSession._eval(clause.element, row)
        if hasattr(clause, "clauses") and clause.clauses:
            results = [_FakeSession._eval(c, row) for c in clause.clauses]
            if getattr(clause, "operator", None) is operators.or_:
                return any(results)
            return all(results)
        op = getattr(clause, "operator", None)
        left = getattr(clause, "left", None)
        if left is None or op is None:
            raise AssertionError(f"cannot evaluate clause: {clause!r}")
        actual = getattr(row, left.key)
        if op is operators.in_op:
            expected = getattr(clause.right, "value", []) or []
            return actual in expected
        right = getattr(clause, "right", None)
        expected = getattr(right, "value", right)
        if op is operators.eq:
            return actual == expected
        if op is operators.ge:
            return actual >= expected
        if op is operators.le:
            return actual <= expected
        raise AssertionError(f"unsupported op: {op!r}")

    def _order_offset_limit(self, statement, rows):
        ordered = sorted(rows, key=lambda r: r.created_at, reverse=True)
        offset = statement._offset or 0
        limit = statement._limit
        self.last_limit = limit
        if limit is None:
            return ordered[offset:]
        return ordered[offset: offset + limit]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_uuids = st.builds(uuid4)


@st.composite
def _log_row(draw, base_time, index):
    """One AuditLog with controllable agency_id/customer_id/action/user/resource."""
    return AuditLog(
        id=uuid4(),
        user_id=draw(_uuids),
        role_type=draw(st.sampled_from(["superadmin", "agencyadmin", "customeradmin"])),
        agency_id=draw(st.one_of(st.none(), _uuids)),
        customer_id=draw(st.one_of(st.none(), _uuids)),
        module=draw(st.text(min_size=1, max_size=8)),
        sub_module=draw(st.text(min_size=1, max_size=8)),
        resource=draw(st.sampled_from(["Campaign", "Template", "Contact", "Order"])),
        action=draw(st.sampled_from(["create", "update", "delete"])),
        old_value={},
        new_value={"x": 1},
        impersonation=False,
        impersonator_user_id=None,
        # Assign distinct created_at values so desc ordering is deterministic.
        created_at=base_time + datetime.timedelta(seconds=index),
    )


@st.composite
def _tenant_ctx(draw):
    role = draw(st.sampled_from(["superadmin", "agencyadmin", "customeradmin"]))
    if role == "superadmin":
        return TenantContext(
            user_id=draw(_uuids), role_type=role,
            agency_scope=None, customer_scope=frozenset(),
            is_superadmin=True, impersonating=False,
            impersonated_agency_id=None, impersonated_customer_id=None,
            impersonator_user_id=None, custom_role_customer_id=None,
        )
    if role == "agencyadmin":
        return TenantContext(
            user_id=draw(_uuids), role_type=role,
            agency_scope=draw(st.one_of(st.none(), _uuids)),
            customer_scope=frozenset(),
            is_superadmin=False, impersonating=False,
            impersonated_agency_id=None, impersonated_customer_id=None,
            impersonator_user_id=None, custom_role_customer_id=None,
        )
    # customeradmin
    customers = draw(st.lists(_uuids, min_size=0, max_size=4, unique=True))
    return TenantContext(
        user_id=draw(_uuids), role_type=role,
        agency_scope=None, customer_scope=frozenset(customers),
        is_superadmin=False, impersonating=False,
        impersonated_agency_id=None, impersonated_customer_id=None,
        impersonator_user_id=None, custom_role_customer_id=None,
    )


@st.composite
def _p30_world(draw):
    """Rows, ctx, filter, page, page_size for Property 30."""
    base_time = datetime.datetime(2024, 1, 1, tzinfo=UTC)
    n = draw(st.integers(min_value=0, max_value=30))
    # Draw a pool of ids so scope and rows can share values (enabling overlap).
    id_pool = [uuid4() for _ in range(max(n, 6))]
    rows = []
    for i in range(n):
        row = AuditLog(
            id=uuid4(),
            user_id=draw(st.sampled_from(id_pool)),
            role_type="customeradmin",
            agency_id=draw(st.one_of(st.none(), st.sampled_from(id_pool))),
            customer_id=draw(st.one_of(st.none(), st.sampled_from(id_pool))),
            module=draw(st.sampled_from(["marketing", "billing", "inventory"])),
            sub_module="sub",
            resource=draw(st.sampled_from(["Campaign", "Template", "Contact"])),
            action=draw(st.sampled_from(["create", "update", "delete"])),
            old_value={},
            new_value={"x": 1},
            impersonation=False,
            impersonator_user_id=None,
            created_at=base_time + datetime.timedelta(seconds=i),
        )
        rows.append(row)
    ctx = draw(_tenant_ctx())
    # Filters — use values drawn from the pool so some rows match some filters.
    flt_action = draw(st.one_of(st.none(), st.sampled_from(["create", "update", "delete"])))
    flt_user = draw(st.one_of(st.none(), st.sampled_from(id_pool))) if id_pool else None
    flt_resource = draw(st.one_of(st.none(), st.sampled_from(["Campaign", "Template"])))
    filters = AuditFilter(action=flt_action, user_id=flt_user, resource=flt_resource)
    page = draw(st.integers(min_value=1, max_value=5))
    page_size = draw(st.integers(min_value=1, max_value=25))
    # Nonce keeps every example distinct (prevents early exhaustion).
    draw(st.integers(min_value=0, max_value=2**30))
    return rows, ctx, filters, page, page_size, id_pool


def _in_scope(row: AuditLog, ctx: TenantContext) -> bool:
    """Reference implementation of audit-specific tenant isolation."""
    if ctx.is_superadmin:
        return True
    if ctx.role_type == "agencyadmin":
        if ctx.agency_scope is None:
            return False
        return row.agency_id == ctx.agency_scope
    # customeradmin / other
    if not ctx.customer_scope:
        return False
    return row.customer_id in ctx.customer_scope


def _matches_filter(row: AuditLog, f: AuditFilter) -> bool:
    """Reference implementation of AND-combined filter matching."""
    if f.action is not None and row.action != f.action:
        return False
    if f.user_id is not None and row.user_id != f.user_id:
        return False
    if f.resource is not None and row.resource != f.resource:
        return False
    if f.module is not None and row.module != f.module:
        return False
    if f.date_from is not None and row.created_at < f.date_from:
        return False
    if f.date_to is not None and row.created_at > f.date_to:
        return False
    return True


# ===========================================================================
# Property 30
# ===========================================================================


# Feature: onella-backend, Property 30: Audit query isolation, filtering, ordering, and pagination
@settings(max_examples=150, deadline=None)
@given(world=_p30_world())
def test_audit_query_isolation_filtering_ordering_pagination(world) -> None:
    """Returned logs are in scope, satisfy all filters, newest first, paginated.

    Validates Requirements 15.1, 15.2, 15.3, 15.4, 15.5.
    """
    rows, ctx, filters, page, page_size, _ = world

    async def run():
        session = _FakeSession(rows)
        service = AuditService(session)
        result = await service.query(ctx, filters, page=page, page_size=page_size)

        # Compute expected items independently.
        in_scope_filtered = [r for r in rows if _in_scope(r, ctx) and _matches_filter(r, filters)]
        expected_ordered = sorted(in_scope_filtered, key=lambda r: r.created_at, reverse=True)
        clamped_ps = max(1, min(page_size, MAX_PAGE_SIZE))
        expected_items = expected_ordered[(page - 1) * clamped_ps: page * clamped_ps]

        # Tenant isolation (Req 15.1-15.3): every returned item is within scope.
        for item in result.items:
            assert _in_scope(item, ctx), (
                f"Item outside scope for {ctx.role_type}: "
                f"agency_id={item.agency_id} customer_id={item.customer_id}"
            )
        # Filter satisfaction (Req 15.4): every returned item matches all filters.
        for item in result.items:
            assert _matches_filter(item, filters), (
                f"Item failed filter: action={item.action} user={item.user_id} resource={item.resource}"
            )
        # Ordering (Req 15.5): timestamps descending.
        for a, b in zip(result.items, result.items[1:]):
            assert a.created_at >= b.created_at

        # Correct page slice.
        assert [r.id for r in result.items] == [r.id for r in expected_items]
        # Correct total count.
        assert result.total == len(in_scope_filtered)
        # Page size clamped.
        assert result.page_size == clamped_ps

    asyncio.run(run())


# Feature: onella-backend, Property 30: Audit query isolation, filtering, ordering, and pagination
@settings(max_examples=100, deadline=None)
@given(
    date_from=st.datetimes(
        min_value=datetime.datetime(2025, 1, 1),
        max_value=datetime.datetime(2025, 12, 31),
    ).map(lambda d: d.replace(tzinfo=UTC)),
    date_to=st.datetimes(
        min_value=datetime.datetime(2024, 1, 1),
        max_value=datetime.datetime(2024, 12, 31),
    ).map(lambda d: d.replace(tzinfo=UTC)),
)
def test_inverted_date_range_rejected(date_from, date_to) -> None:
    """date_from > date_to always raises InvalidDateRangeError (Req 15.4)."""
    # date_from is 2025, date_to is 2024 → always inverted.
    assert date_from > date_to
    ctx = TenantContext(
        user_id=uuid4(), role_type="superadmin",
        agency_scope=None, customer_scope=frozenset(),
        is_superadmin=True, impersonating=False,
        impersonated_agency_id=None, impersonated_customer_id=None,
        impersonator_user_id=None, custom_role_customer_id=None,
    )
    async def run():
        service = AuditService(_FakeSession([]))
        with pytest.raises(InvalidDateRangeError):
            await service.query(ctx, AuditFilter(date_from=date_from, date_to=date_to))
    asyncio.run(run())


# ===========================================================================
# Property 31
# ===========================================================================


@st.composite
def _p31_world(draw):
    """Rows, ctx, format, and a nonce for Property 31."""
    base_time = datetime.datetime(2024, 3, 1, tzinfo=UTC)
    n = draw(st.integers(min_value=0, max_value=20))
    rows = [
        AuditLog(
            id=uuid4(), user_id=uuid4(), role_type="customeradmin",
            agency_id=None, customer_id=None,
            module="marketing", sub_module="campaign", resource="Campaign",
            action=draw(st.sampled_from(["create", "update", "delete"])),
            old_value={}, new_value={"x": 1},
            impersonation=False, impersonator_user_id=None,
            created_at=base_time + datetime.timedelta(seconds=i),
        )
        for i in range(n)
    ]
    fmt = draw(st.sampled_from(["csv", "json"]))
    ctx = TenantContext(
        user_id=uuid4(), role_type="superadmin",
        agency_scope=None, customer_scope=frozenset(),
        is_superadmin=True, impersonating=False,
        impersonated_agency_id=None, impersonated_customer_id=None,
        impersonator_user_id=None, custom_role_customer_id=None,
    )
    draw(st.integers(min_value=0, max_value=2**30))  # distinctness nonce
    return rows, ctx, fmt


# Feature: onella-backend, Property 31: Audit export format and cap
@settings(max_examples=150, deadline=None)
@given(world=_p31_world())
def test_audit_export_format_and_cap(world) -> None:
    """Output is valid CSV or JSON, newest-first, capped at 100k (Req 15.6)."""
    rows, ctx, fmt = world

    async def run():
        session = _FakeSession(rows)
        service = AuditService(session)
        payload = await service.export(ctx, fmt=fmt)

        # The service applies EXPORT_MAX_RECORDS as the LIMIT (Req 15.6).
        assert session.last_limit == EXPORT_MAX_RECORDS

        expected_count = min(len(rows), EXPORT_MAX_RECORDS)

        if fmt == "json":
            data = json.loads(payload.decode("utf-8"))
            assert isinstance(data, list)
            assert len(data) == expected_count
            if len(data) > 1:
                # Newest first (Req 15.6).
                created_ats = [d["created_at"] for d in data]
                assert created_ats == sorted(created_ats, reverse=True)
        else:  # csv
            reader = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
            assert len(reader) == expected_count + 1  # header + data rows
            assert reader[0][0] == "id"  # first header field
            if len(reader) > 2:
                # created_at is the last column (index -1), newest first.
                created_ats = [row[-1] for row in reader[1:] if row]
                assert created_ats == sorted(created_ats, reverse=True)

    asyncio.run(run())

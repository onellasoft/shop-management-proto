"""Unit tests for :meth:`AuditService.query` (Task 22.1, Req 15.1-15.5).

Verifies audit-specific tenant isolation, AND-combined filtering, inverted
date-range rejection, ``created_at`` descending ordering, and pagination
(default 50 / max 200 clamp) against an **in-memory fake AsyncSession** that
genuinely filters stored :class:`AuditLog` rows.

Rather than assert compiled SQL, the fake session evaluates each statement's
WHERE clause against the stored rows via SQLAlchemy's own column accessors and
applies the ordering / offset / limit the service builds — so isolation and
filtering are exercised end to end. It also answers the ``SELECT count(*) FROM
(<scoped+filtered subquery>)`` the service issues for the page total.
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest

from app.core.errors import InvalidDateRangeError
from app.core.tenant_context import TenantContext
from app.models.audit import AuditLog
from app.services.audit_service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AuditFilter,
    AuditService,
)

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# In-memory fake AsyncSession that filters/orders/paginates AuditLog rows
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _Result:
    def __init__(self, *, scalar_rows=None, scalar_value=None) -> None:
        self._scalar_rows = scalar_rows
        self._scalar_value = scalar_value

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._scalar_rows or [])

    def scalar_one(self):
        return self._scalar_value


class _FakeSession:
    """AsyncSession stand-in backed by in-memory :class:`AuditLog` rows."""

    def __init__(self, rows: list[AuditLog]) -> None:
        self.rows = list(rows)

    async def execute(self, statement):  # noqa: ANN001
        # A count query is ``select(func.count()).select_from(<subquery>)``.
        if self._is_count(statement):
            subq = statement.get_final_froms()[0]
            matched = self._filter(subq.element)
            return _Result(scalar_value=len(matched))

        # Otherwise it is the paginated select(AuditLog).
        matched = self._filter(statement)
        matched = self._order_offset_limit(statement, matched)
        return _Result(scalar_rows=matched)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _is_count(statement) -> bool:
        # The count select has no column entity (it is func.count()).
        descriptions = statement.column_descriptions
        return not descriptions or descriptions[0].get("entity") is not AuditLog

    def _filter(self, statement) -> list[AuditLog]:
        whereclause = statement.whereclause
        return [r for r in self.rows if self._matches(whereclause, r)]

    @staticmethod
    def _matches(whereclause, row) -> bool:
        if whereclause is None:
            return True
        return _FakeSession._eval(whereclause, row)

    @staticmethod
    def _eval(clause, row) -> bool:
        from sqlalchemy.sql import operators

        # Boolean literal (false()) used for fail-closed scoping.
        if clause.__class__.__name__ == "False_":
            return False

        # ``.where(false())`` wraps the literal in an AsBoolean; unwrap it.
        if clause.__class__.__name__ == "AsBoolean":
            return _FakeSession._eval(clause.element, row)

        # Composite AND/OR clause.
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

        # IN (...) — right is a single expanding BindParameter whose value is
        # the list of members.
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
        raise AssertionError(f"unsupported operator in fake: {op!r}")

    @staticmethod
    def _order_offset_limit(statement, rows: list[AuditLog]) -> list[AuditLog]:
        # created_at desc ordering (the only order the service emits).
        ordered = sorted(rows, key=lambda r: r.created_at, reverse=True)
        offset = statement._offset or 0
        limit = statement._limit
        if limit is None:
            return ordered[offset:]
        return ordered[offset : offset + limit]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _ctx(
    *,
    role_type: str,
    agency_scope: UUID | None = None,
    customer_scope: frozenset[UUID] = frozenset(),
    is_superadmin: bool = False,
) -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
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


def _log(
    *,
    agency_id: UUID | None = None,
    customer_id: UUID | None = None,
    action: str = "create",
    user_id: UUID | None = None,
    resource: str = "MessageTemplate",
    module: str = "marketing",
    created_at: datetime.datetime | None = None,
) -> AuditLog:
    row = AuditLog(
        user_id=user_id or uuid4(),
        role_type="customeradmin",
        agency_id=agency_id,
        customer_id=customer_id,
        module=module,
        sub_module="campaign",
        resource=resource,
        action=action,
        old_value=None,
        new_value={"x": 1},
        impersonation=False,
        impersonator_user_id=None,
        created_at=created_at or datetime.datetime(2024, 1, 1, tzinfo=UTC),
    )
    row.id = uuid4()
    return row


# ---------------------------------------------------------------------------
# Tenant isolation (Req 15.1-15.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_superadmin_sees_all_logs():
    """Req 15.1 — superadmin gets every log, no tenant boundary."""
    rows = [_log(agency_id=uuid4(), customer_id=uuid4()) for _ in range(5)]
    service = AuditService(_FakeSession(rows))
    page = await service.query(_ctx(role_type="superadmin", is_superadmin=True))
    assert page.total == 5
    assert len(page.items) == 5


@pytest.mark.asyncio
async def test_agencyadmin_scoped_by_agency_id():
    """Req 15.2 — agencyadmin sees only their agency's logs."""
    agency = uuid4()
    other_agency = uuid4()
    mine = [_log(agency_id=agency, customer_id=uuid4()) for _ in range(3)]
    theirs = [_log(agency_id=other_agency, customer_id=uuid4()) for _ in range(2)]
    service = AuditService(_FakeSession(mine + theirs))

    page = await service.query(_ctx(role_type="agencyadmin", agency_scope=agency))

    assert page.total == 3
    assert all(item.agency_id == agency for item in page.items)


@pytest.mark.asyncio
async def test_agencyadmin_without_agency_scope_sees_nothing():
    """Req 15.2 — missing agency scope fails closed (zero rows)."""
    rows = [_log(agency_id=uuid4(), customer_id=uuid4()) for _ in range(3)]
    service = AuditService(_FakeSession(rows))
    page = await service.query(_ctx(role_type="agencyadmin", agency_scope=None))
    assert page.total == 0
    assert page.items == []


@pytest.mark.asyncio
async def test_customeradmin_scoped_by_customer_id_in_scope():
    """Req 15.3 — customeradmin sees only their assigned customers' logs."""
    c1, c2, other = uuid4(), uuid4(), uuid4()
    mine = [_log(agency_id=uuid4(), customer_id=c1), _log(customer_id=c2)]
    theirs = [_log(agency_id=uuid4(), customer_id=other)]
    service = AuditService(_FakeSession(mine + theirs))

    page = await service.query(
        _ctx(role_type="customeradmin", customer_scope=frozenset({c1, c2}))
    )

    assert page.total == 2
    assert {item.customer_id for item in page.items} == {c1, c2}


@pytest.mark.asyncio
async def test_customeradmin_empty_scope_sees_nothing():
    """Req 15.3 — empty customer scope fails closed (IN () → zero rows)."""
    rows = [_log(customer_id=uuid4()) for _ in range(3)]
    service = AuditService(_FakeSession(rows))
    page = await service.query(
        _ctx(role_type="customeradmin", customer_scope=frozenset())
    )
    assert page.total == 0


# ---------------------------------------------------------------------------
# AND-combined filters (Req 15.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filters_are_and_combined():
    """Req 15.4 — every specified filter must match (AND)."""
    user = uuid4()
    match = _log(action="update", user_id=user, resource="Invoice")
    wrong_action = _log(action="create", user_id=user, resource="Invoice")
    wrong_user = _log(action="update", user_id=uuid4(), resource="Invoice")
    wrong_resource = _log(action="update", user_id=user, resource="Template")
    service = AuditService(
        _FakeSession([match, wrong_action, wrong_user, wrong_resource])
    )

    page = await service.query(
        _ctx(role_type="superadmin", is_superadmin=True),
        AuditFilter(action="update", user_id=user, resource="Invoice"),
    )

    assert page.total == 1
    assert page.items[0].id == match.id


@pytest.mark.asyncio
async def test_date_range_filter_is_inclusive():
    """Req 15.4 — created_at within [from, to] inclusive."""
    early = _log(created_at=datetime.datetime(2024, 1, 1, tzinfo=UTC))
    mid = _log(created_at=datetime.datetime(2024, 6, 1, tzinfo=UTC))
    late = _log(created_at=datetime.datetime(2024, 12, 1, tzinfo=UTC))
    service = AuditService(_FakeSession([early, mid, late]))

    page = await service.query(
        _ctx(role_type="superadmin", is_superadmin=True),
        AuditFilter(
            date_from=datetime.datetime(2024, 3, 1, tzinfo=UTC),
            date_to=datetime.datetime(2024, 9, 1, tzinfo=UTC),
        ),
    )

    assert page.total == 1
    assert page.items[0].id == mid.id


@pytest.mark.asyncio
async def test_inverted_date_range_is_rejected():
    """Req 15.4 — start later than end raises InvalidDateRangeError."""
    service = AuditService(_FakeSession([]))
    with pytest.raises(InvalidDateRangeError):
        await service.query(
            _ctx(role_type="superadmin", is_superadmin=True),
            AuditFilter(
                date_from=datetime.datetime(2024, 9, 1, tzinfo=UTC),
                date_to=datetime.datetime(2024, 3, 1, tzinfo=UTC),
            ),
        )


@pytest.mark.asyncio
async def test_equal_date_range_is_allowed():
    """Req 15.4 — equal from/to is a valid (single-instant) range."""
    same = datetime.datetime(2024, 5, 5, tzinfo=UTC)
    service = AuditService(_FakeSession([_log(created_at=same)]))
    page = await service.query(
        _ctx(role_type="superadmin", is_superadmin=True),
        AuditFilter(date_from=same, date_to=same),
    )
    assert page.total == 1


# ---------------------------------------------------------------------------
# Ordering + pagination (Req 15.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_results_ordered_by_created_at_desc():
    """Req 15.5 — newest first."""
    a = _log(created_at=datetime.datetime(2024, 1, 1, tzinfo=UTC))
    b = _log(created_at=datetime.datetime(2024, 2, 1, tzinfo=UTC))
    c = _log(created_at=datetime.datetime(2024, 3, 1, tzinfo=UTC))
    service = AuditService(_FakeSession([a, b, c]))
    page = await service.query(_ctx(role_type="superadmin", is_superadmin=True))
    assert [item.id for item in page.items] == [c.id, b.id, a.id]


@pytest.mark.asyncio
async def test_default_page_size_is_50():
    """Req 15.5 — default page size 50."""
    rows = [
        _log(created_at=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(seconds=i))
        for i in range(60)
    ]
    service = AuditService(_FakeSession(rows))
    page = await service.query(_ctx(role_type="superadmin", is_superadmin=True))
    assert page.page_size == DEFAULT_PAGE_SIZE
    assert len(page.items) == 50
    assert page.total == 60
    assert page.has_more is True


@pytest.mark.asyncio
async def test_page_size_clamped_to_max_200():
    """Req 15.5 — an over-large page size is clamped to 200 (not rejected)."""
    service = AuditService(_FakeSession([_log() for _ in range(3)]))
    page = await service.query(
        _ctx(role_type="superadmin", is_superadmin=True), page_size=5000
    )
    assert page.page_size == MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_second_page_offsets_correctly():
    """Req 15.5 — page 2 returns the next slice."""
    rows = [
        _log(created_at=datetime.datetime(2024, 1, 1, tzinfo=UTC) + datetime.timedelta(seconds=i))
        for i in range(5)
    ]
    service = AuditService(_FakeSession(rows))
    page = await service.query(
        _ctx(role_type="superadmin", is_superadmin=True), page=2, page_size=2
    )
    # Ordered desc: seconds 4,3,2,1,0 → page 2 (size 2) is seconds 2,1.
    assert page.page == 2
    assert len(page.items) == 2
    assert page.has_more is True  # 5 total, 2*2=4 < 5


@pytest.mark.asyncio
async def test_non_positive_page_size_falls_back_to_default():
    """A page size <= 0 falls back to the default rather than erroring."""
    service = AuditService(_FakeSession([_log()]))
    page = await service.query(
        _ctx(role_type="superadmin", is_superadmin=True), page_size=0
    )
    assert page.page_size == DEFAULT_PAGE_SIZE

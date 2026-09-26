"""Property-based test for tenant isolation (no cross-tenant data access).

# Feature: onella-backend, Property 19: No cross-tenant data access

**Validates: Requirements 9.2, 9.7, 4.2, 4.4**

Property 19 (design): *For any* data set and any authenticated user, every
record returned by a query and every record affected by a mutation falls within
the user's tenant context; any attempt to read or mutate data outside the
tenant context returns no data, performs no mutation, and yields a
tenant-boundary error. A superadmin has no boundary and sees all tenants.

These tests exercise the REAL tenant isolation helpers implemented in Task 14.1
(:func:`app.db.tenant_query.tenant_query` and
:func:`app.db.tenant_query.verify_tenant_scope`) over Hypothesis-generated
worlds, without a live database.

Two complementary angles are covered:

1. **Read path (filtering invariant).** ``tenant_query(model, ctx)`` is invoked
   for real, and its *compiled* WHERE clause is evaluated in Python against each
   generated row via :class:`_ClauseEvaluator` — a small, test-only clause
   interpreter that understands the exact operators ``tenant_query`` emits
   (``col.in_(...)`` for the customer path, ``col == scope`` for the agency
   path, and ``false()`` for the fail-closed default), plus AND/OR. This runs
   the production WHERE builder against arbitrary data and collects the admitted
   rows, then asserts:

   * (a) every admitted row is within the context's scope;
   * (b) no in-scope row is omitted (admitted set == expected in-scope set);
   * (c) a superadmin admits every row (no boundary — Req 4.2, 9.3);
   * (d) a non-superadmin with an empty ``customer_scope`` admits none
     (fail-closed — Req 9.7).

2. **Mutation path (re-verification invariant).** ``verify_tenant_scope`` is
   invoked for real for each generated row + context, asserting it returns
   ``None`` exactly when the row is within scope and raises
   :class:`~app.core.errors.TenantBoundaryViolationError` otherwise; a
   superadmin always passes (Req 4.2/4.4/9.2/9.7).

The "expected in-scope" set is computed from the documented scoping rules
independently of the SQL the function emits, so the test genuinely cross-checks
the production behavior rather than restating it.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import operators

from app.core.errors import TenantBoundaryViolationError
from app.core.tenant_context import TenantContext
from app.db.mixins import TenantMixin
from app.db.tenant_query import tenant_query, verify_tenant_scope


# ---------------------------------------------------------------------------
# Lightweight test models on isolated metadata (no Base.metadata pollution).
# Mirrors tests/unit/test_tenant_query.py.
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class CustomerScoped(TenantMixin, _TestBase):
    """A model carrying both tenant columns; customer_id takes precedence."""

    __tablename__ = "cq_prop_customer_scoped"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class AgencyScoped(_TestBase):
    """A model carrying only an agency_id column (no customer_id)."""

    __tablename__ = "cq_prop_agency_scoped"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class NoTenant(_TestBase):
    """A model with neither tenant column — must fail closed."""

    __tablename__ = "cq_prop_no_tenant"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# In-memory row stand-ins. These expose ``customer_id`` / ``agency_id``
# attributes so the compiled clause can be evaluated against them by column key.
# ---------------------------------------------------------------------------


class _CustomerRow:
    def __init__(self, customer_id: uuid.UUID, agency_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.customer_id = customer_id
        # A customer row also carries an agency_id; tenant_query on CustomerScoped
        # ignores it (customer_id precedence), but we keep it realistic.
        self.agency_id = agency_id


class _AgencyRow:
    def __init__(self, agency_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.agency_id = agency_id


# ---------------------------------------------------------------------------
# Clause evaluator — a minimal, test-only interpreter for the *exact* WHERE
# shapes tenant_query emits. It runs the REAL compiled statement's whereclause
# against an in-memory row, so we exercise production filtering, not a copy.
# ---------------------------------------------------------------------------


class _ClauseEvaluator:
    """Evaluate a compiled SQLAlchemy WHERE clause against an in-memory row.

    Supports the operators tenant_query produces:

    * ``col.in_([...])`` (customer path — including the empty-IN case),
    * ``col == value`` (agency path),
    * ``false()`` (fail-closed default),
    * boolean ``AND`` / ``OR`` groupings (for completeness/robustness).
    """

    @staticmethod
    def matches(statement, row) -> bool:
        whereclause = statement.whereclause
        if whereclause is None:
            # No filter at all → admits every row (superadmin path).
            return True
        return _ClauseEvaluator._eval(whereclause, row)

    @staticmethod
    def _eval(clause, row) -> bool:
        op = getattr(clause, "operator", None)

        # Boolean groupings (AND/OR over sub-clauses).
        if op in (operators.and_, operators.or_) and getattr(clause, "clauses", None):
            results = [_ClauseEvaluator._eval(c, row) for c in clause.clauses]
            return any(results) if op is operators.or_ else all(results)

        # Literal false() — the fail-closed default matches nothing.
        # SQLAlchemy renders it as a constant with no left/right operands.
        left = getattr(clause, "left", None)
        if left is None:
            # A bare False_ / boolean constant. Treat any non-comparison,
            # operand-less clause as the fail-closed contradiction.
            return False

        right = getattr(clause, "right", None)
        actual = getattr(row, left.key)

        # IN — the customer path: col.in_(customer_scope).
        if op is operators.in_op:
            candidates = _ClauseEvaluator._in_values(right)
            return actual in candidates

        # Equality — the agency path: col == agency_scope.
        if op in (operators.eq, operators.is_):
            expected = _ClauseEvaluator._scalar(right)
            return actual == expected
        if op in (operators.ne, operators.is_not):
            expected = _ClauseEvaluator._scalar(right)
            return actual != expected

        raise AssertionError(f"unsupported operator in evaluator: {op!r}")

    @staticmethod
    def _scalar(right):
        return getattr(right, "value", right)

    @staticmethod
    def _in_values(right) -> set:
        """Extract the concrete value set from the right side of an IN clause.

        SQLAlchemy represents ``col.in_([...])`` right-hand side either as an
        expanding bindparam whose ``.value`` is the sequence, or as a grouping
        of bindparams/literals. Handle both, and the empty-IN case.
        """
        # Expanding bindparam: right.value holds the sequence directly.
        value = getattr(right, "value", None)
        if isinstance(value, (list, tuple, set, frozenset)):
            return set(value)

        # Grouping of individual bind params / literals.
        clauses = getattr(right, "clauses", None)
        if clauses is not None:
            out = set()
            for c in clauses:
                out.add(getattr(c, "value", c))
            return out

        # A single scalar bind (single-element IN) or empty.
        if value is not None:
            return {value}
        return set()


# ---------------------------------------------------------------------------
# TenantContext factory (mirrors the unit tests).
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


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_uuids = st.builds(uuid.uuid4)


@st.composite
def _customer_world(draw: st.DrawFn):
    """A customer-scoped world: rows tagged with a customer_id drawn from a
    small id pool, plus a context whose customer_scope is a subset of the pool.

    Reusing a bounded id pool guarantees overlap between rows and scope so both
    the "admitted" and "excluded" branches get exercised, instead of every
    fresh uuid4 falling outside the scope.
    """
    # A shared pool so rows and scope can overlap meaningfully.
    pool = draw(st.lists(_uuids, min_size=1, max_size=6, unique=True))
    agencies = draw(st.lists(_uuids, min_size=1, max_size=3, unique=True))

    rows = [
        _CustomerRow(
            customer_id=draw(st.sampled_from(pool)),
            agency_id=draw(st.sampled_from(agencies)),
        )
        for _ in range(draw(st.integers(min_value=0, max_value=8)))
    ]

    # The scope is an arbitrary subset of the pool (possibly empty → fail-closed).
    scope = frozenset(
        draw(st.lists(st.sampled_from(pool), min_size=0, max_size=len(pool), unique=True))
    )
    role_type = draw(st.sampled_from(["customeradmin", "agencyadmin"]))
    ctx = _ctx(
        role_type=role_type,
        agency_scope=None,
        customer_scope=scope,
        is_superadmin=False,
    )
    return rows, ctx


@st.composite
def _agency_world(draw: st.DrawFn):
    """An agency-scoped world: AgencyScoped rows tagged from an id pool, plus an
    agencyadmin context scoped to one agency in (or occasionally out of) the
    pool."""
    pool = draw(st.lists(_uuids, min_size=1, max_size=5, unique=True))
    rows = [
        _AgencyRow(agency_id=draw(st.sampled_from(pool)))
        for _ in range(draw(st.integers(min_value=0, max_value=8)))
    ]
    # Usually pick an agency from the pool (so some rows match); occasionally an
    # unrelated agency (so none match) to exercise the empty result.
    scope = draw(
        st.one_of(st.sampled_from(pool), _uuids)
    )
    ctx = _ctx(
        role_type="agencyadmin",
        agency_scope=scope,
        customer_scope=frozenset(),
        is_superadmin=False,
    )
    return rows, ctx


@st.composite
def _superadmin_customer_world(draw: st.DrawFn):
    """Arbitrary customer rows viewed by a superadmin (must admit all)."""
    pool = draw(st.lists(_uuids, min_size=1, max_size=6, unique=True))
    agencies = draw(st.lists(_uuids, min_size=1, max_size=3, unique=True))
    rows = [
        _CustomerRow(
            customer_id=draw(st.sampled_from(pool)),
            agency_id=draw(st.sampled_from(agencies)),
        )
        for _ in range(draw(st.integers(min_value=0, max_value=8)))
    ]
    return rows, _ctx(
        role_type="superadmin",
        agency_scope=None,
        customer_scope=frozenset(),
        is_superadmin=True,
    )


@st.composite
def _read_case(draw: st.DrawFn):
    """One read-path world of a Hypothesis-chosen kind, tagged with its kind.

    A single composite over a continuous space keeps Hypothesis spending its
    full example budget rather than concluding the space is exhausted early.
    """
    kind = draw(
        st.sampled_from(["customer", "agency", "superadmin", "no_tenant"])
    )
    # Structural nonce keeps every example distinct.
    draw(st.integers(min_value=0, max_value=1_000_000))
    if kind == "customer":
        rows, ctx = draw(_customer_world())
        return ("customer", rows, ctx)
    if kind == "agency":
        rows, ctx = draw(_agency_world())
        return ("agency", rows, ctx)
    if kind == "superadmin":
        rows, ctx = draw(_superadmin_customer_world())
        return ("superadmin", rows, ctx)
    # no_tenant — a model that cannot be scoped for a non-superadmin.
    rows = [
        type("Row", (), {"id": uuid.uuid4(), "name": "x"})()
        for _ in range(draw(st.integers(min_value=0, max_value=5)))
    ]
    ctx = _ctx(
        role_type="customeradmin",
        agency_scope=None,
        customer_scope=frozenset(draw(st.lists(_uuids, min_size=0, max_size=3))),
        is_superadmin=False,
    )
    return ("no_tenant", rows, ctx)


# ===========================================================================
# Property 19 (core) — No cross-tenant data access
# ===========================================================================


# Feature: onella-backend, Property 19: No cross-tenant data access
@settings(max_examples=200, deadline=None)
@given(case=_read_case())
def test_no_cross_tenant_data_access(case) -> None:
    """Every row admitted by tenant_query's WHERE is within scope, no in-scope
    row is dropped, superadmin admits all, and fail-closed admits none.

    Validates Requirements 9.2, 9.7, 4.2, 4.4.
    """
    kind, rows, ctx = case

    if kind == "customer":
        stmt = tenant_query(CustomerScoped, ctx)
        admitted = [r for r in rows if _ClauseEvaluator.matches(stmt, r)]
        expected = [r for r in rows if r.customer_id in ctx.customer_scope]

        # (a) every admitted row is within the context's scope.
        for r in admitted:
            assert r.customer_id in ctx.customer_scope
        # (b) no in-scope row is omitted.
        assert {id(r) for r in admitted} == {id(r) for r in expected}
        # (d) empty customer_scope for a non-superadmin admits nothing.
        if not ctx.customer_scope:
            assert admitted == []
        return

    if kind == "agency":
        stmt = tenant_query(AgencyScoped, ctx)
        admitted = [r for r in rows if _ClauseEvaluator.matches(stmt, r)]
        expected = [r for r in rows if r.agency_id == ctx.agency_scope]

        for r in admitted:
            assert r.agency_id == ctx.agency_scope
        assert {id(r) for r in admitted} == {id(r) for r in expected}
        return

    if kind == "superadmin":
        stmt = tenant_query(CustomerScoped, ctx)
        admitted = [r for r in rows if _ClauseEvaluator.matches(stmt, r)]
        # (c) superadmin has no boundary — every row is admitted (Req 4.2, 9.3).
        assert {id(r) for r in admitted} == {id(r) for r in rows}
        assert stmt.whereclause is None
        return

    # kind == "no_tenant" — fail-closed: a model that cannot be tenant-scoped
    # for a non-superadmin must match nothing (Req 9.7).
    stmt = tenant_query(NoTenant, ctx)
    admitted = [r for r in rows if _ClauseEvaluator.matches(stmt, r)]
    assert admitted == []


# ===========================================================================
# Mutation path — verify_tenant_scope re-verification invariant
# ===========================================================================


@st.composite
def _verify_case(draw: st.DrawFn):
    """A row identifier + context for the mutation re-verification invariant."""
    pool = draw(st.lists(_uuids, min_size=1, max_size=6, unique=True))
    kind = draw(st.sampled_from(["customer", "agency", "none"]))
    is_superadmin = draw(st.booleans())

    scope = frozenset(
        draw(st.lists(st.sampled_from(pool), min_size=0, max_size=len(pool), unique=True))
    )
    agency_scope = draw(st.one_of(st.sampled_from(pool), _uuids, st.none()))

    ctx = _ctx(
        role_type="superadmin" if is_superadmin else "customeradmin",
        agency_scope=None if is_superadmin else agency_scope,
        customer_scope=frozenset() if is_superadmin else scope,
        is_superadmin=is_superadmin,
    )

    if kind == "customer":
        return ctx, {"customer_id": draw(st.sampled_from(pool))}
    if kind == "agency":
        return ctx, {"agency_id": draw(st.one_of(st.sampled_from(pool), _uuids))}
    return ctx, {}


# Feature: onella-backend, Property 19: No cross-tenant data access
@settings(max_examples=200, deadline=None)
@given(case=_verify_case())
def test_verify_tenant_scope_matches_boundary(case) -> None:
    """verify_tenant_scope passes iff the row is within scope; superadmin always
    passes; otherwise it raises TenantBoundaryViolationError (no mutation).

    Validates Requirements 9.2, 9.7, 4.2, 4.4.
    """
    ctx, ids = case
    customer_id = ids.get("customer_id")
    agency_id = ids.get("agency_id")

    # Determine expected outcome from the documented rules, independent of the
    # function's internals.
    if ctx.is_superadmin:
        expected_ok = True
    elif customer_id is not None:
        expected_ok = customer_id in ctx.customer_scope
    elif agency_id is not None:
        expected_ok = ctx.agency_scope is not None and agency_id == ctx.agency_scope
    else:
        # No tenant identifier for a non-superadmin — fail closed.
        expected_ok = False

    if expected_ok:
        # Returns None (no exception) when within scope.
        assert (
            verify_tenant_scope(
                ctx=ctx, agency_id=agency_id, customer_id=customer_id
            )
            is None
        )
    else:
        with pytest.raises(TenantBoundaryViolationError):
            verify_tenant_scope(
                ctx=ctx, agency_id=agency_id, customer_id=customer_id
            )

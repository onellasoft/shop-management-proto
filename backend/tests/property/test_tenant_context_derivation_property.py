"""Property-based tests for tenant-context derivation and missing scope.

# Feature: onella-backend, Property 18: Derived tenant context matches role and assignments

**Validates: Requirements 9.1, 4.3, 4.5, 9.3, 9.4, 9.5, 9.6**

# Feature: onella-backend, Property 20: Missing tenant scope is rejected

**Validates: Requirements 9.8**

These tests exercise :meth:`AuthorizationService.build_tenant_context`
(implemented in Task 13.1) directly, over Hypothesis-generated worlds.

* **Property 18** — for any authenticated user, the derived
  :class:`~app.core.tenant_context.TenantContext` equals the expected scope for
  the user's role: unbounded for ``superadmin``; exactly the customers under the
  single agency for ``agencyadmin``; exactly the assigned customers (possibly
  spanning agencies, at least one) for ``customeradmin``; and the single scoping
  customer when acting under a custom role.

* **Property 20** — for any authenticated non-superadmin request whose agency or
  customer scope cannot be derived (agencyadmin with no ``agency_id``,
  customeradmin with zero assignments, or an unknown ``role_type``), the request
  is rejected with :class:`~app.core.errors.TenantContextMissingError` and no
  context is produced.

The database boundary reuses the in-memory fake ``AsyncSession`` pattern
established in ``tests/unit/test_authorization_service_build_context.py`` — it
evaluates the two query shapes ``build_tenant_context`` issues
(``select(Customer.id).where(Customer.agency_id == ...)`` and
``select(CustomerUser.customer_id).where(CustomerUser.user_id == ...)``) against
in-memory rows, so the service's real filtering runs without a live Postgres.
Because ``build_tenant_context`` is ``async`` and Hypothesis drives synchronous
test bodies, each example runs the coroutine to completion via ``asyncio.run``;
the fake session performs no real I/O, so 100+ iterations stay fast.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.cache.customer_list_cache import AgencyCustomerListCache
from app.core.errors import TenantContextMissingError
from app.core.security import ACCESS_TOKEN_TYPE, AccessTokenClaims
from app.models.customer import Customer
from app.models.customer_user import CustomerUser
from app.services.authorization_service import AuthorizationService

# Reuse the established in-memory fake AsyncSession pattern from the unit tests,
# plus the in-memory customer-list cache backend so the agencyadmin scope path
# (Task 15.1, Req 10) never reaches a live Redis server.
from tests.unit.test_authorization_service_build_context import (
    _FakeSession,
    _InMemoryCustomerListBackend,
)


# ---------------------------------------------------------------------------
# Helpers (mirroring the unit-test fixtures)
# ---------------------------------------------------------------------------


def _claims(
    role_type: str,
    *,
    user_id: UUID | None = None,
    agency_id: UUID | None = None,
    customer_id: UUID | None = None,
) -> AccessTokenClaims:
    return AccessTokenClaims(
        sub=user_id or uuid4(),
        email="user@example.com",
        role_type=role_type,
        agency_id=agency_id,
        customer_id=customer_id,
        iat=0,
        exp=0,
        token_type=ACCESS_TOKEN_TYPE,
    )


def _customer(customer_id: UUID, agency_id: UUID) -> Customer:
    c = Customer(agency_id=agency_id, name="Biz")
    c.id = customer_id
    return c


def _assignment(user_id: UUID, customer_id: UUID) -> CustomerUser:
    cu = CustomerUser(user_id=user_id, customer_id=customer_id)
    cu.id = uuid4()
    return cu


def _build(session: _FakeSession, claims: AccessTokenClaims, **kwargs):
    """Run the async builder to completion synchronously for Hypothesis.

    A FRESH in-memory customer-list cache is injected per call so the
    agencyadmin scope path resolves through the Req 10 cache without touching a
    real Redis server. Because the cache starts cold on every example, the
    agencyadmin branch always falls through to the ``_FakeSession`` DB read —
    exactly the behaviour the property asserts against (expected == actual
    scope derived from the fake session's customers).
    """
    cache = AgencyCustomerListCache(_InMemoryCustomerListBackend())
    svc = AuthorizationService(session, customer_list_cache=cache)
    return asyncio.run(svc.build_tenant_context(claims, **kwargs))


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Distinct UUIDs. Drawing fresh uuid4()s keeps ids globally unique across a
# world, so scope-set equality is unambiguous.
_uuids = st.builds(uuid4)


@st.composite
def _superadmin_world(draw: st.DrawFn):
    """A superadmin plus arbitrary unrelated rows (which must be ignored)."""
    user = draw(_uuids)
    # Populate the session with noise the superadmin branch must never consult.
    noise_agency = draw(_uuids)
    customers = [
        _customer(draw(_uuids), noise_agency)
        for _ in range(draw(st.integers(min_value=0, max_value=4)))
    ]
    assignments = [
        _assignment(user, draw(_uuids))
        for _ in range(draw(st.integers(min_value=0, max_value=4)))
    ]
    session = _FakeSession(customers=customers, customer_users=assignments)
    return session, _claims("superadmin", user_id=user)


@st.composite
def _agencyadmin_world(draw: st.DrawFn):
    """An agencyadmin whose scope must equal its own agency's customers."""
    agency = draw(_uuids)
    other_agency = draw(_uuids)
    # 0..5 customers under this agency (empty agency is a valid empty scope).
    own_ids = draw(
        st.lists(_uuids, min_size=0, max_size=5, unique=True)
    )
    own = [_customer(cid, agency) for cid in own_ids]
    # Customers under a different agency must be excluded from the scope.
    other = [
        _customer(draw(_uuids), other_agency)
        for _ in range(draw(st.integers(min_value=0, max_value=4)))
    ]
    session = _FakeSession(customers=own + other)
    expected = frozenset(own_ids)
    return session, _claims("agencyadmin", agency_id=agency), expected


@st.composite
def _customeradmin_world(draw: st.DrawFn):
    """A customeradmin with 1..N assigned customers, possibly across agencies."""
    user = draw(_uuids)
    other_user = draw(_uuids)
    # At least one assignment — a customeradmin with none is a rejection case.
    assigned_ids = draw(
        st.lists(_uuids, min_size=1, max_size=6, unique=True)
    )
    mine = [_assignment(user, cid) for cid in assigned_ids]
    # Assignments belonging to a different user must be excluded.
    theirs = [
        _assignment(other_user, draw(_uuids))
        for _ in range(draw(st.integers(min_value=0, max_value=4)))
    ]
    session = _FakeSession(customer_users=mine + theirs)
    expected = frozenset(assigned_ids)
    return session, _claims("customeradmin", user_id=user), expected


@st.composite
def _custom_role_world(draw: st.DrawFn):
    """A non-superadmin acting under a custom role scoped to one customer."""
    user = draw(_uuids)
    scoping_customer = draw(_uuids)
    role_type = draw(st.sampled_from(["agencyadmin", "customeradmin"]))
    # Underlying assignments/customers exist but must be collapsed away by the
    # custom-role branch, which short-circuits before role-specific derivation.
    session = _FakeSession(
        customers=[_customer(draw(_uuids), draw(_uuids))],
        customer_users=[
            _assignment(user, draw(_uuids))
            for _ in range(draw(st.integers(min_value=0, max_value=3)))
        ],
    )
    agency = draw(_uuids) if role_type == "agencyadmin" else None
    claims = _claims(role_type, user_id=user, agency_id=agency)
    return session, claims, scoping_customer


# ===========================================================================
# Property 18 — Derived tenant context matches role and assignments
# ===========================================================================

@st.composite
def _p18_case(draw: st.DrawFn):
    """One world of a Hypothesis-chosen role, tagged with its kind.

    A single composite (rather than a ``one_of`` over discrete branch labels)
    keeps the generated space continuous and large — each role path draws
    several fresh UUIDs and variable-length lists — so Hypothesis spends its
    full example budget instead of concluding the space is exhausted early.
    """
    kind = draw(
        st.sampled_from(
            ["superadmin", "agencyadmin", "customeradmin", "custom_role"]
        )
    )
    # A structurally-varying nonce keeps every example distinct so Hypothesis
    # does not treat the world space as exhausted and terminate before its full
    # example budget (the required 100+ iterations) is spent.
    draw(st.text(min_size=0, max_size=8))
    if kind == "superadmin":
        return ("superadmin", draw(_superadmin_world()))
    if kind == "agencyadmin":
        return ("agencyadmin", draw(_agencyadmin_world()))
    if kind == "customeradmin":
        return ("customeradmin", draw(_customeradmin_world()))
    return ("custom_role", draw(_custom_role_world()))


# Feature: onella-backend, Property 18: Derived tenant context matches role and assignments
@settings(max_examples=200, deadline=None)
@given(case=_p18_case())
def test_derived_context_matches_role_and_assignments(case) -> None:
    """The derived context equals the expected scope for the user's role.

    Validates Requirements 9.1, 4.3, 4.5, 9.3, 9.4, 9.5, 9.6.
    """
    kind, payload = case

    if kind == "superadmin":
        session, claims = payload
        ctx = _build(session, claims)
        # Req 4.2 / 9.3 — unbounded: superadmin flag set, empty (no-filter)
        # customer_scope, no agency_scope, no custom-role collapse.
        assert ctx.is_superadmin is True
        assert ctx.agency_scope is None
        assert ctx.customer_scope == frozenset()
        assert ctx.custom_role_customer_id is None
        assert ctx.user_id == claims.sub
        assert ctx.role_type == "superadmin"
        return

    if kind == "agencyadmin":
        session, claims, expected = payload
        ctx = _build(session, claims)
        # Req 4.3 / 9.4 — exactly the customers under the single agency.
        assert ctx.is_superadmin is False
        assert ctx.agency_scope == claims.agency_id
        assert ctx.customer_scope == expected
        assert ctx.custom_role_customer_id is None
        return

    if kind == "customeradmin":
        session, claims, expected = payload
        ctx = _build(session, claims)
        # Req 4.5 / 9.5 — exactly the assigned customers, possibly across
        # agencies; no agency_scope; at least one customer.
        assert ctx.is_superadmin is False
        assert ctx.agency_scope is None
        assert ctx.customer_scope == expected
        assert len(ctx.customer_scope) >= 1
        assert ctx.custom_role_customer_id is None
        return

    # kind == "custom_role" — Req 9.6: scope collapses to the single customer.
    session, claims, scoping_customer = payload
    ctx = _build(session, claims, custom_role_customer_id=scoping_customer)
    assert ctx.is_superadmin is False
    assert ctx.agency_scope is None
    assert ctx.customer_scope == frozenset({scoping_customer})
    assert ctx.custom_role_customer_id == scoping_customer


# ===========================================================================
# Property 20 — Missing tenant scope is rejected
# ===========================================================================


@st.composite
def _agencyadmin_no_agency(draw: st.DrawFn):
    """agencyadmin without an agency_id — no derivable scope (Req 9.8)."""
    # Arbitrary customer rows exist but no agency binds the principal to them.
    session = _FakeSession(
        customers=[
            _customer(draw(_uuids), draw(_uuids))
            for _ in range(draw(st.integers(min_value=0, max_value=4)))
        ]
    )
    return session, _claims("agencyadmin", agency_id=None)


@st.composite
def _customeradmin_no_customers(draw: st.DrawFn):
    """customeradmin with zero assignments for this user (Req 4.5 / 9.8)."""
    user = draw(_uuids)
    other_user = draw(_uuids)
    # Only assignments for *other* users exist, so this user resolves to none.
    assignments = [
        _assignment(other_user, draw(_uuids))
        for _ in range(draw(st.integers(min_value=0, max_value=5)))
    ]
    session = _FakeSession(customer_users=assignments)
    return session, _claims("customeradmin", user_id=user)


@st.composite
def _unknown_role(draw: st.DrawFn):
    """An unrecognized role_type — fail-closed (Req 9.8)."""
    role_type = draw(
        st.text(min_size=1, max_size=20).filter(
            lambda s: s not in {"superadmin", "agencyadmin", "customeradmin"}
        )
    )
    session = _FakeSession(
        customers=[
            _customer(draw(_uuids), draw(_uuids))
            for _ in range(draw(st.integers(min_value=0, max_value=3)))
        ]
    )
    return session, _claims(role_type, agency_id=draw(_uuids))


@st.composite
def _p20_case(draw: st.DrawFn):
    """One non-derivable non-superadmin world, drawn evenly across the three
    rejection kinds so each (agencyadmin-without-agency, customeradmin-without-
    customers, unknown-role) is meaningfully exercised."""
    kind = draw(st.sampled_from(["no_agency", "no_customers", "unknown_role"]))
    if kind == "no_agency":
        return draw(_agencyadmin_no_agency())
    if kind == "no_customers":
        return draw(_customeradmin_no_customers())
    return draw(_unknown_role())


_p20_cases = _p20_case()


# Feature: onella-backend, Property 20: Missing tenant scope is rejected
@settings(max_examples=150, deadline=None)
@given(case=_p20_cases)
def test_missing_tenant_scope_is_rejected(case) -> None:
    """Non-derivable non-superadmin requests raise TenantContextMissingError.

    Validates Requirement 9.8. No context is produced (the builder raises before
    returning), so no scope is ever derived for these requests.
    """
    session, claims = case
    with pytest.raises(TenantContextMissingError):
        _build(session, claims)

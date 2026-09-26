"""Property-based tests for impersonated-boundary and sensitive-action gates.

# Feature: onella-backend, Property 23: Impersonated boundary is always enforced

**Validates: Requirements 12.1, 12.2, 12.3**

# Feature: onella-backend, Property 25: Sensitive actions are always blocked during impersonation

**Validates: Requirements 13.2, 13.3, 13.4**

These are the security-critical impersonation properties. Each exercises the
REAL production code paths — no logic is re-implemented in the test:

* **Property 23** drives the actual impersonated-context construction
  (:meth:`AuthorizationService.build_tenant_context` with an ``impersonation``
  state, Task 18.1), the real tenant filter
  (:func:`app.db.tenant_query.tenant_query` /
  :func:`app.db.tenant_query.verify_tenant_scope`, Task 14.1), and the real
  indicator builder (:meth:`ImpersonationService.build_indicator`). Over
  Hypothesis-generated impersonation states (customer target and agency target)
  and data rows it asserts, for every example, that:

  - the derived context has ``impersonating=True`` and ``is_superadmin=False``,
    and its ``customer_scope`` / ``agency_scope`` are those of the IMPERSONATED
    entity — never the impersonator's — even when the impersonator is a
    superadmin (Req 12.1);
  - feeding that context to ``tenant_query`` admits only rows inside the
    impersonated boundary, and ``verify_tenant_scope`` raises
    :class:`TenantBoundaryViolationError` for a row outside it — i.e. no
    mutation of out-of-boundary data (Req 12.2);
  - the indicator identifies the impersonated entity by type + id (Req 12.3).

* **Property 25** drives the REAL sensitive-action gate through
  :func:`require_permission`'s dependency end-to-end via a FastAPI app +
  ``TestClient`` (mirroring ``tests/unit/test_require_permission_sensitive.py``),
  with only the DB-facing seams stubbed (``deps._load_action``,
  ``AuthorizationService.has_permission`` / ``is_module_usable``). Over
  Hypothesis-generated ``(is_sensitive, has_permission, impersonating)``
  combinations it asserts:

  - impersonating & sensitive → rejected with
    ``action_restricted_during_impersonation``, handler never runs (Req 13.2);
  - impersonating & non-sensitive → outcome equals the normal
    permission/tenant decision — allowed iff the grant is present (Req 13.3);
  - not impersonating → the sensitive flag never triggers an impersonation
    rejection (a sensitive action with the grant is allowed);
  - flag-change (Req 13.4) → because ``_load_action`` reads the Action per
    request, flipping ``is_sensitive`` flips the outcome on the next request.

The database boundary reuses the in-memory fake ``AsyncSession`` /
customer-list-cache pattern from
``tests/unit/test_authorization_service_build_context.py`` so the agency-target
impersonation scope resolves without a live Redis, and the whole suite runs with
no live DB/Redis. Because ``build_tenant_context`` is ``async`` and Hypothesis
drives synchronous bodies, each Property 23 example runs its coroutine to
completion via ``asyncio.run`` with FRESH fakes (mirroring
``tests/property/test_tenant_context_derivation_property.py``). Property 25 is a
synchronous Hypothesis test driving the ``TestClient``.

If any counterexample revealed that the impersonated boundary was NOT enforced
or a sensitive action slipped through, that would be a real security bug — these
tests fail loudly rather than working around it.
"""

from __future__ import annotations

import asyncio
import uuid
from uuid import UUID, uuid4

import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi import Depends, FastAPI, Request
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import operators
from starlette.testclient import TestClient

import app.api.deps as deps
from app.api.deps import require_permission
from app.cache.customer_list_cache import AgencyCustomerListCache
from app.core.errors import (
    TenantBoundaryViolationError,
    register_exception_handlers,
)
from app.core.security import ACCESS_TOKEN_TYPE, AccessTokenClaims
from app.core.tenant_context import TenantContext
from app.db.mixins import TenantMixin
from app.db.session import get_db
from app.db.tenant_query import tenant_query, verify_tenant_scope
from app.models.customer import Customer
from app.models.impersonation import ImpersonationSession
from app.models.permission import Action
from app.services.authorization_service import AuthorizationService
from app.services.impersonation_service import ImpersonationService

# Reuse the established in-memory fakes so the agency-target impersonation scope
# derivation (Req 10 cache path) resolves entirely in memory — no live Redis.
from tests.unit.test_authorization_service_build_context import (
    _FakeSession,
    _InMemoryCustomerListBackend,
)


# ===========================================================================
# Shared helpers
# ===========================================================================


def _claims(
    role_type: str,
    *,
    user_id: UUID,
    agency_id: UUID | None = None,
    customer_id: UUID | None = None,
) -> AccessTokenClaims:
    return AccessTokenClaims(
        sub=user_id,
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


class _Impersonation:
    """Minimal :class:`ImpersonationState` stand-in (mirrors the model XOR).

    Exposes exactly the three attributes ``build_tenant_context`` reads: the
    impersonated target (exactly one of agency/customer set) and the real acting
    (impersonator) user id.
    """

    def __init__(
        self,
        *,
        impersonated_agency_id: UUID | None = None,
        impersonated_customer_id: UUID | None = None,
        impersonator_user_id: UUID,
    ) -> None:
        self.impersonated_agency_id = impersonated_agency_id
        self.impersonated_customer_id = impersonated_customer_id
        self.impersonator_user_id = impersonator_user_id


def _build_impersonated_context(
    session: _FakeSession,
    claims: AccessTokenClaims,
    impersonation: _Impersonation,
) -> TenantContext:
    """Run the REAL async builder to completion with FRESH fakes per example.

    A fresh in-memory customer-list cache is injected so the agency-target scope
    path resolves through the Req 10 cache without a live Redis. The cache
    starts cold each example, so the agency branch always falls through to the
    ``_FakeSession`` DB read — exactly what the property asserts against.
    """
    cache = AgencyCustomerListCache(_InMemoryCustomerListBackend())
    svc = AuthorizationService(session, customer_list_cache=cache)
    return asyncio.run(
        svc.build_tenant_context(claims, impersonation=impersonation)
    )


_uuids = st.builds(uuid4)


# ===========================================================================
# Property 23 — Impersonated boundary is always enforced
# ===========================================================================
#
# A lightweight tenant-scoped model on isolated metadata (does not pollute
# Base.metadata) plus a minimal WHERE-clause evaluator, mirroring
# tests/property/test_no_cross_tenant_access_property.py. tenant_query builds
# the REAL statement; the evaluator runs its compiled WHERE against in-memory
# rows so the production filter is exercised, not a copy.


class _TestBase(DeclarativeBase):
    pass


class _CustomerScoped(TenantMixin, _TestBase):
    """A customer-scoped model (customer_id takes precedence over agency_id)."""

    __tablename__ = "imp_prop_customer_scoped"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class _Row:
    """In-memory row exposing customer_id / agency_id by column key."""

    def __init__(self, customer_id: UUID, agency_id: UUID) -> None:
        self.id = uuid4()
        self.customer_id = customer_id
        self.agency_id = agency_id


class _ClauseEvaluator:
    """Evaluate a compiled ``tenant_query`` WHERE clause against a row.

    Understands the exact shapes ``tenant_query`` emits: ``col.in_([...])`` (the
    customer path, including empty-IN), ``col == value`` (the agency path),
    ``false()`` (fail-closed default), plus AND/OR groupings. Copied from
    ``tests/property/test_no_cross_tenant_access_property.py`` so the same
    production statement is exercised.
    """

    @staticmethod
    def matches(statement, row) -> bool:
        whereclause = statement.whereclause
        if whereclause is None:
            return True  # no filter → admits every row (superadmin only)
        return _ClauseEvaluator._eval(whereclause, row)

    @staticmethod
    def _eval(clause, row) -> bool:
        op = getattr(clause, "operator", None)
        if op in (operators.and_, operators.or_) and getattr(
            clause, "clauses", None
        ):
            results = [_ClauseEvaluator._eval(c, row) for c in clause.clauses]
            return any(results) if op is operators.or_ else all(results)

        left = getattr(clause, "left", None)
        if left is None:
            # A bare boolean constant (false()) — fail-closed, matches nothing.
            return False

        right = getattr(clause, "right", None)
        actual = getattr(row, left.key)

        if op is operators.in_op:
            return actual in _ClauseEvaluator._in_values(right)
        if op in (operators.eq, operators.is_):
            return actual == _ClauseEvaluator._scalar(right)
        if op in (operators.ne, operators.is_not):
            return actual != _ClauseEvaluator._scalar(right)
        raise AssertionError(f"unsupported operator in evaluator: {op!r}")

    @staticmethod
    def _scalar(right):
        return getattr(right, "value", right)

    @staticmethod
    def _in_values(right) -> set:
        value = getattr(right, "value", None)
        if isinstance(value, (list, tuple, set, frozenset)):
            return set(value)
        clauses = getattr(right, "clauses", None)
        if clauses is not None:
            return {getattr(c, "value", c) for c in clauses}
        if value is not None:
            return {value}
        return set()


def _make_session_row(
    *,
    impersonated_agency_id: UUID | None,
    impersonated_customer_id: UUID | None,
    impersonator: UUID,
    started_at,
) -> ImpersonationSession:
    """A real :class:`ImpersonationSession` for the indicator builder."""
    row = ImpersonationSession(
        impersonator_user_id=impersonator,
        impersonated_agency_id=impersonated_agency_id,
        impersonated_customer_id=impersonated_customer_id,
        active=True,
        started_at=started_at,
    )
    row.id = uuid4()
    return row


@st.composite
def _p23_case(draw: st.DrawFn):
    """One impersonation world: a customer target or an agency target.

    Returns ``(kind, session, claims, impersonation, indicator_session,
    payload)`` where ``payload`` carries the data needed to check the tenant
    filter for that kind.

    The impersonator is drawn as an arbitrary role INCLUDING superadmin so the
    "even a superadmin drops to the impersonated boundary" invariant (Req 12.1)
    is exercised.
    """
    kind = draw(st.sampled_from(["customer", "agency"]))
    # Nonce keeps each example distinct so Hypothesis spends its full budget.
    draw(st.integers(min_value=0, max_value=1_000_000))

    impersonator = draw(_uuids)
    # The impersonator's OWN role/agency — deliberately unrelated to the target
    # so we can prove the derived scope is the impersonated entity's, not this.
    role = draw(st.sampled_from(["superadmin", "agencyadmin", "customeradmin"]))
    own_agency = draw(_uuids) if role == "agencyadmin" else None
    claims = _claims(
        role, user_id=impersonator, agency_id=own_agency
    )
    started_at = draw(
        st.datetimes(
            min_value=__import__("datetime").datetime(2020, 1, 1),
            max_value=__import__("datetime").datetime(2030, 1, 1),
        )
    )

    if kind == "customer":
        target_customer = draw(_uuids)
        # A distinct out-of-boundary customer id for the negative filter check.
        outside_customer = draw(_uuids.filter(lambda c: c != target_customer))
        session = _FakeSession()  # customer target needs no DB scope resolution
        impersonation = _Impersonation(
            impersonated_customer_id=target_customer,
            impersonator_user_id=impersonator,
        )
        indicator_session = _make_session_row(
            impersonated_agency_id=None,
            impersonated_customer_id=target_customer,
            impersonator=impersonator,
            started_at=started_at,
        )
        payload = {
            "target_customer": target_customer,
            "outside_customer": outside_customer,
        }
        return ("customer", session, claims, impersonation, indicator_session, payload)

    # agency target — the impersonated agency's customers are resolved from the
    # fake session's Customer rows (via resolve_agency_customer_ids).
    target_agency = draw(_uuids)
    other_agency = draw(_uuids.filter(lambda a: a != target_agency))
    in_ids = draw(st.lists(_uuids, min_size=0, max_size=4, unique=True))
    out_ids = draw(st.lists(_uuids, min_size=0, max_size=3, unique=True))
    customers = [_customer(cid, target_agency) for cid in in_ids]
    customers += [_customer(cid, other_agency) for cid in out_ids]
    session = _FakeSession(customers=customers)
    impersonation = _Impersonation(
        impersonated_agency_id=target_agency,
        impersonator_user_id=impersonator,
    )
    indicator_session = _make_session_row(
        impersonated_agency_id=target_agency,
        impersonated_customer_id=None,
        impersonator=impersonator,
        started_at=started_at,
    )
    payload = {
        "target_agency": target_agency,
        "other_agency": other_agency,
        "in_ids": frozenset(in_ids),
    }
    return ("agency", session, claims, impersonation, indicator_session, payload)


# Feature: onella-backend, Property 23: Impersonated boundary is always enforced
@settings(max_examples=150, deadline=None)
@given(case=_p23_case())
def test_impersonated_boundary_is_always_enforced(case) -> None:
    """The impersonated entity's boundary is enforced end-to-end.

    Validates Requirements 12.1, 12.2, 12.3.
    """
    kind, session, claims, impersonation, indicator_session, payload = case

    # --- Context construction (Task 18.1, Req 12.1) --------------------------
    ctx = _build_impersonated_context(session, claims, impersonation)

    # The impersonator ALWAYS drops to the impersonated boundary — even a
    # superadmin loses its unbounded scope (Req 12.1).
    assert ctx.impersonating is True
    assert ctx.is_superadmin is False
    # The real acting user is recorded (for audit), but the ENFORCED scope is
    # the impersonated entity's, not the impersonator's.
    assert ctx.impersonator_user_id == impersonation.impersonator_user_id
    assert ctx.user_id == claims.sub

    # --- Indicator (Req 12.3) ------------------------------------------------
    indicator = ImpersonationService(session).build_indicator(indicator_session)
    assert indicator["impersonating"] is True

    if kind == "customer":
        target = payload["target_customer"]
        outside = payload["outside_customer"]

        # Context collapses to exactly the impersonated customer (Req 12.1).
        assert ctx.customer_scope == frozenset({target})
        assert ctx.agency_scope is None
        assert ctx.impersonated_customer_id == target
        assert ctx.impersonated_agency_id is None

        # Indicator identifies the impersonated customer by type + id (Req 12.3).
        assert indicator["impersonated_type"] == "customer"
        assert indicator["impersonated_id"] == str(target)

        # Read path: only rows inside the impersonated boundary are admitted,
        # and a row outside it is excluded (Req 12.2).
        stmt = tenant_query(_CustomerScoped, ctx)
        in_row = _Row(customer_id=target, agency_id=uuid4())
        out_row = _Row(customer_id=outside, agency_id=uuid4())
        assert _ClauseEvaluator.matches(stmt, in_row) is True
        assert _ClauseEvaluator.matches(stmt, out_row) is False

        # Mutation path: re-verification passes inside, raises outside — no
        # mutation of out-of-boundary data (Req 12.2).
        assert verify_tenant_scope(ctx=ctx, customer_id=target) is None
        with pytest.raises(TenantBoundaryViolationError):
            verify_tenant_scope(ctx=ctx, customer_id=outside)
        return

    # kind == "agency"
    target_agency = payload["target_agency"]
    in_ids = payload["in_ids"]

    # Context scopes to the impersonated agency and exactly its customers
    # (resolved from the impersonated entity, not the impersonator) (Req 12.1).
    assert ctx.agency_scope == target_agency
    assert ctx.customer_scope == in_ids
    assert ctx.impersonated_agency_id == target_agency
    assert ctx.impersonated_customer_id is None

    # Indicator identifies the impersonated agency by type + id (Req 12.3).
    assert indicator["impersonated_type"] == "agency"
    assert indicator["impersonated_id"] == str(target_agency)

    # Read path over customer-scoped data: every in-agency customer is admitted;
    # any customer NOT under the impersonated agency is excluded (Req 12.2).
    stmt = tenant_query(_CustomerScoped, ctx)
    for cid in in_ids:
        assert _ClauseEvaluator.matches(stmt, _Row(cid, target_agency)) is True
    stranger = uuid4()
    assert stranger not in in_ids
    assert _ClauseEvaluator.matches(stmt, _Row(stranger, target_agency)) is False

    # Mutation path: a customer inside the boundary passes; one outside raises
    # (no mutation) (Req 12.2).
    for cid in in_ids:
        assert verify_tenant_scope(ctx=ctx, customer_id=cid) is None
    with pytest.raises(TenantBoundaryViolationError):
        verify_tenant_scope(ctx=ctx, customer_id=stranger)


# ===========================================================================
# Property 25 — Sensitive actions are always blocked during impersonation
# ===========================================================================
#
# Drives the REAL require_permission dependency end-to-end via a TestClient,
# stubbing only the DB seams (deps._load_action, has_permission,
# is_module_usable), mirroring tests/unit/test_require_permission_sensitive.py.

ACTION_KEY = "inventory.items.things.update"


def _make_action(*, is_sensitive: bool) -> Action:
    action = Action(
        resource_id=uuid.uuid4(),
        name="update",
        is_sensitive=is_sensitive,
        action_key=ACTION_KEY,
    )
    action.__dict__["_module_id"] = uuid.uuid4()
    return action


def _context(*, impersonating: bool, is_superadmin: bool) -> TenantContext:
    customer = uuid.uuid4()
    impersonator = uuid.uuid4() if impersonating else None
    return TenantContext(
        user_id=impersonator or uuid.uuid4(),
        role_type="customeradmin",
        agency_scope=None,
        customer_scope=frozenset({customer}),
        is_superadmin=is_superadmin,
        impersonating=impersonating,
        impersonated_agency_id=None,
        impersonated_customer_id=customer if impersonating else None,
        impersonator_user_id=impersonator,
        custom_role_customer_id=None,
    )


class _NoopSession:
    """A stand-in AsyncSession; never queried because the DB seams are stubbed."""


def _build_app(ctx: TenantContext) -> tuple[FastAPI, dict]:
    """Minimal app: one route guarded by require_permission + a side-effect flag.

    ``state["handler_ran"]`` is flipped ONLY if the guarded handler executes —
    the "perform no mutation" marker (Req 13.2).
    """
    app = FastAPI()
    register_exception_handlers(app)
    state = {"handler_ran": False}

    @app.middleware("http")
    async def _attach_context(request: Request, call_next):  # noqa: ANN001
        request.state.tenant_context = ctx
        return await call_next(request)

    @app.post("/_probe/guarded")
    async def _guarded(
        _ctx: TenantContext = Depends(require_permission(ACTION_KEY)),
    ):
        state["handler_ran"] = True
        return {"ok": True}

    async def _fake_get_db():
        yield _NoopSession()

    app.dependency_overrides[get_db] = _fake_get_db
    return app, state


@st.composite
def _p25_case(draw: st.DrawFn):
    """One sensitive-gate scenario plus a follow-up flag flip.

    Draws the full ``(is_sensitive, has_permission, impersonating,
    is_superadmin)`` combination that governs a single request AND a
    ``flipped_sensitive`` value used for a *second* request that re-reads the
    Action — so Req 13.2, 13.3 and 13.4 are all exercised by the one property.

    A large integer ``nonce`` is drawn so the input space is effectively
    unbounded: without it the four booleans form only 16 distinct inputs and
    Hypothesis would stop after exhausting them (~16 examples), well short of
    the required 100+ iterations. The nonce keeps every example distinct so
    Hypothesis spends its full ``max_examples`` budget.

    ``is_superadmin`` is only meaningfully paired with ``impersonating=False``:
    while impersonating the boundary drop (Task 18.1) forces
    ``is_superadmin=False``, which the caller enforces.
    """
    draw(st.integers(min_value=0, max_value=2**60))  # distinctness nonce
    return {
        "is_sensitive": draw(st.booleans()),
        "has_permission": draw(st.booleans()),
        "impersonating": draw(st.booleans()),
        "is_superadmin": draw(st.booleans()),
        "flipped_sensitive": draw(st.booleans()),
    }


def _patch_db_seams(
    mp: MonkeyPatch,
    *,
    has_permission: bool,
    is_sensitive_provider,
) -> None:
    """Stub the three DB-facing seams the gate reaches (no live DB).

    ``is_sensitive_provider`` is a zero-arg callable so a per-request flag flip
    (Req 13.4) can be honoured on each ``_load_action`` call.
    """

    async def _has_permission(self, ctx, action_key):  # noqa: ANN001
        return has_permission

    async def _usable(self, customer_id, module_id):  # noqa: ANN001
        return True  # module gate never masks the behaviour under test

    async def _load(db, action_key):  # noqa: ANN001
        return _make_action(is_sensitive=is_sensitive_provider())

    mp.setattr(AuthorizationService, "has_permission", _has_permission)
    mp.setattr(AuthorizationService, "is_module_usable", _usable)
    mp.setattr(deps, "_load_action", _load)


def _expected_outcome(
    *, is_sensitive: bool, impersonating: bool, permission_ok: bool
) -> str:
    """The gate's expected result for a single request.

    Encodes the REAL gate order in ``deps.require_permission``:
    (1) permission check → (2) module gate → (3) sensitive gate. A missing grant
    denies first with ``not_authorized`` (pre-empting the sensitive gate); with
    the grant present, a sensitive action while impersonating is blocked by the
    sensitive gate; otherwise the request is allowed.
    """
    if not permission_ok:
        return "not_authorized"
    if impersonating and is_sensitive:
        return "restricted"
    return "allowed"


def _assert_outcome(resp, state: dict, expected: str) -> None:
    if expected == "restricted":
        assert resp.status_code == 403
        assert (
            resp.json()["error"]["code"]
            == "action_restricted_during_impersonation"
        )
        assert state["handler_ran"] is False
    elif expected == "not_authorized":
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "not_authorized"
        assert state["handler_ran"] is False
    else:  # allowed
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert state["handler_ran"] is True


# Feature: onella-backend, Property 25: Sensitive actions are always blocked during impersonation
@settings(max_examples=150, deadline=None)
@given(case=_p25_case())
def test_sensitive_actions_are_always_blocked_during_impersonation(case) -> None:
    """The sensitive gate blocks a sensitive action during impersonation, passes
    non-sensitive actions through the normal checks, never rejects on
    sensitivity outside impersonation, and honours a per-request flag change.

    Validates Requirements 13.2, 13.3, 13.4.

    Drives the REAL :func:`require_permission` dependency end-to-end through a
    ``TestClient``; only the DB seams (``deps._load_action``,
    ``has_permission``, ``is_module_usable``) are stubbed. A per-example
    :class:`MonkeyPatch` context (rather than the function-scoped ``monkeypatch``
    fixture, which Hypothesis rejects for ``@given`` bodies) patches/unpatches
    those seams independently for every generated example.
    """
    is_sensitive = case["is_sensitive"]
    has_permission = case["has_permission"]
    impersonating = case["impersonating"]
    flipped_sensitive = case["flipped_sensitive"]
    # While impersonating, the boundary drop forces is_superadmin False; only
    # honour the drawn superadmin flag when NOT impersonating.
    is_superadmin = case["is_superadmin"] and not impersonating
    # A superadmin bypasses the permission check; anyone else needs the grant.
    permission_ok = is_superadmin or has_permission

    # ``_load_action`` reads the Action per request (no caching), so a mutable
    # provider lets the SECOND request observe a flipped ``is_sensitive`` — the
    # Req 13.4 flag-change behaviour, exercised within this same property.
    flag = {"is_sensitive": is_sensitive}

    mp = MonkeyPatch()
    try:
        _patch_db_seams(
            mp,
            has_permission=has_permission,
            is_sensitive_provider=lambda: flag["is_sensitive"],
        )

        ctx = _context(impersonating=impersonating, is_superadmin=is_superadmin)
        app, state = _build_app(ctx)
        client = TestClient(app)

        # --- Request 1: the drawn scenario ---------------------------------
        state["handler_ran"] = False
        resp1 = client.post("/_probe/guarded")
        expected1 = _expected_outcome(
            is_sensitive=is_sensitive,
            impersonating=impersonating,
            permission_ok=permission_ok,
        )
        _assert_outcome(resp1, state, expected1)

        # Security invariant (Req 13.2): a sensitive action is NEVER executed
        # while impersonating, whichever 403 fired.
        if impersonating and is_sensitive:
            assert state["handler_ran"] is False
        # Req 13.3 corollary: outside impersonation the sensitive flag never
        # causes an impersonation rejection — with the grant it is allowed.
        if not impersonating and permission_ok:
            assert resp1.status_code == 200

        # --- Request 2: flip is_sensitive (Req 13.4) -----------------------
        # The Action is re-read, so the outcome tracks the NEW flag on the very
        # next request; every other input (context, grant) is unchanged.
        flag["is_sensitive"] = flipped_sensitive
        state["handler_ran"] = False
        resp2 = client.post("/_probe/guarded")
        expected2 = _expected_outcome(
            is_sensitive=flipped_sensitive,
            impersonating=impersonating,
            permission_ok=permission_ok,
        )
        _assert_outcome(resp2, state, expected2)
    finally:
        mp.undo()

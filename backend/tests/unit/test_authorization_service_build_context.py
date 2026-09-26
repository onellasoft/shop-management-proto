"""Unit tests for ``AuthorizationService.build_tenant_context`` (Task 13.1).

Covers tenant-scope derivation for every role plus the rejection cases
(Req 9.1, 4.2, 4.3, 4.5, 9.3, 9.4, 9.5, 9.6, 9.8):

* **superadmin** — unbounded: ``is_superadmin=True``, empty ``customer_scope``
  (= no filter), ``agency_scope=None`` (Req 4.2, 9.3).
* **agencyadmin** — ``agency_scope`` set to the user's agency and
  ``customer_scope`` = every Customer under that Agency (Req 4.3, 9.4).
* **customeradmin** — ``customer_scope`` = the Customers assigned via
  ``customer_users``, which may span Agencies (Req 4.5, 9.5).
* **custom role** — scope collapses to the single ``custom_role_customer_id``
  (Req 9.6).
* rejection — agencyadmin without an agency, and customeradmin with no assigned
  customers, raise :class:`TenantContextMissingError` (Req 9.8).

The database boundary is an in-memory fake ``AsyncSession`` that interprets the
two query shapes ``build_tenant_context`` issues:

* ``select(Customer.id).where(Customer.agency_id == ...)``
* ``select(CustomerUser.customer_id).where(CustomerUser.user_id == ...)``

evaluating each statement's compiled WHERE clause against stored rows via
SQLAlchemy's own column accessors, so the service's real filtering runs without
a live Postgres database (the models use Postgres-specific types).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.cache.customer_list_cache import AgencyCustomerListCache
from app.core.errors import TenantContextMissingError
from app.core.security import ACCESS_TOKEN_TYPE, AccessTokenClaims
from app.models.customer import Customer
from app.models.customer_user import CustomerUser
from app.services.authorization_service import AuthorizationService


# ---------------------------------------------------------------------------
# In-memory fake AsyncSession
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _Result:
    def __init__(self, scalar_rows: list) -> None:
        self._scalar_rows = scalar_rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._scalar_rows)


class _FakeSession:
    """AsyncSession stand-in backed by in-memory ``Customer``/``CustomerUser``."""

    def __init__(
        self,
        customers: list[Customer] | None = None,
        customer_users: list[CustomerUser] | None = None,
    ) -> None:
        self.customers: list[Customer] = list(customers or [])
        self.customer_users: list[CustomerUser] = list(customer_users or [])

    async def execute(self, statement):  # noqa: ANN001
        entity = statement.column_descriptions[0]["entity"]
        if entity is Customer:
            matched = [c for c in self.customers if self._matches(statement, c)]
            return _Result([c.id for c in matched])
        if entity is CustomerUser:
            matched = [
                cu for cu in self.customer_users if self._matches(statement, cu)
            ]
            return _Result([cu.customer_id for cu in matched])
        raise AssertionError(f"unexpected entity in statement: {entity}")

    @staticmethod
    def _matches(statement, row) -> bool:
        whereclause = statement.whereclause
        if whereclause is None:
            return True
        return _FakeSession._eval(whereclause, row)

    @staticmethod
    def _eval(clause, row) -> bool:
        from sqlalchemy.sql import operators

        if hasattr(clause, "clauses") and clause.clauses:
            results = [_FakeSession._eval(c, row) for c in clause.clauses]
            if clause.operator is operators.or_:
                return any(results)
            return all(results)

        op = getattr(clause, "operator", None)
        left = getattr(clause, "left", None)
        right = getattr(clause, "right", None)
        if left is None or op is None:
            raise AssertionError(f"cannot evaluate clause: {clause!r}")

        actual = getattr(row, left.key)
        expected = getattr(right, "value", right)
        if op in (operators.eq, operators.is_):
            return actual == expected
        if op in (operators.ne, operators.is_not):
            return actual != expected
        raise AssertionError(f"unsupported operator in fake: {op!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InMemoryCustomerListBackend:
    """In-memory ``CustomerListBackend`` fake (no time-driven TTL expiry)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self.data[key] = value

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)


def _service(session) -> AuthorizationService:
    # Inject an in-memory customer-list cache so agencyadmin scope derivation
    # (which now resolves through the Req 10 cache) runs without a live Redis.
    cache = AgencyCustomerListCache(_InMemoryCustomerListBackend())
    return AuthorizationService(session, customer_list_cache=cache)


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


# ===========================================================================
# superadmin — unbounded (Req 4.2, 9.3)
# ===========================================================================


async def test_superadmin_context_is_unbounded():
    user = uuid4()
    svc = _service(_FakeSession())

    ctx = await svc.build_tenant_context(_claims("superadmin", user_id=user))

    assert ctx.is_superadmin is True
    assert ctx.customer_scope == frozenset()  # empty = no filter
    assert ctx.agency_scope is None
    assert ctx.custom_role_customer_id is None
    assert ctx.user_id == user
    assert ctx.role_type == "superadmin"
    assert ctx.impersonating is False


# ===========================================================================
# agencyadmin — scoped to its agency's customers (Req 4.3, 9.4)
# ===========================================================================


async def test_agencyadmin_scoped_to_agency_customers():
    agency = uuid4()
    other_agency = uuid4()
    c1, c2 = uuid4(), uuid4()
    session = _FakeSession(
        customers=[
            _customer(c1, agency),
            _customer(c2, agency),
            _customer(uuid4(), other_agency),  # different agency — excluded
        ]
    )
    svc = _service(session)

    ctx = await svc.build_tenant_context(
        _claims("agencyadmin", agency_id=agency)
    )

    assert ctx.is_superadmin is False
    assert ctx.agency_scope == agency
    assert ctx.customer_scope == frozenset({c1, c2})
    assert ctx.custom_role_customer_id is None


async def test_agencyadmin_with_no_customers_still_scoped_to_agency():
    # An Agency with zero Customers is a derivable (empty) boundary: the
    # agencyadmin is legitimately scoped to its single Agency.
    agency = uuid4()
    svc = _service(_FakeSession(customers=[]))

    ctx = await svc.build_tenant_context(
        _claims("agencyadmin", agency_id=agency)
    )

    assert ctx.agency_scope == agency
    assert ctx.customer_scope == frozenset()


async def test_agencyadmin_without_agency_is_rejected():
    # Req 9.8 — no agency_id means no derivable scope.
    svc = _service(_FakeSession())
    with pytest.raises(TenantContextMissingError):
        await svc.build_tenant_context(_claims("agencyadmin", agency_id=None))


# ===========================================================================
# customeradmin — assigned customers, possibly across agencies (Req 4.5, 9.5)
# ===========================================================================


async def test_customeradmin_scoped_to_assigned_customers_across_agencies():
    user = uuid4()
    # Two customers assigned to this user; belong to different agencies.
    c1, c2 = uuid4(), uuid4()
    # A third assignment for a *different* user must be excluded.
    other_user = uuid4()
    c3 = uuid4()
    session = _FakeSession(
        customer_users=[
            _assignment(user, c1),
            _assignment(user, c2),
            _assignment(other_user, c3),
        ]
    )
    svc = _service(session)

    ctx = await svc.build_tenant_context(
        _claims("customeradmin", user_id=user)
    )

    assert ctx.is_superadmin is False
    assert ctx.agency_scope is None
    assert ctx.customer_scope == frozenset({c1, c2})
    assert ctx.custom_role_customer_id is None


async def test_customeradmin_with_no_customers_is_rejected():
    # Req 4.5 / 9.8 — a customeradmin needs at least one assigned Customer.
    svc = _service(_FakeSession(customer_users=[]))
    with pytest.raises(TenantContextMissingError):
        await svc.build_tenant_context(_claims("customeradmin"))


# ===========================================================================
# custom role — single-customer scope (Req 9.6)
# ===========================================================================


async def test_custom_role_collapses_scope_to_single_customer():
    user = uuid4()
    customer = uuid4()
    # Even though the underlying customeradmin has other assignments, acting
    # under a custom role collapses scope to that role's single customer.
    session = _FakeSession(
        customer_users=[
            _assignment(user, customer),
            _assignment(user, uuid4()),
        ]
    )
    svc = _service(session)

    ctx = await svc.build_tenant_context(
        _claims("customeradmin", user_id=user),
        custom_role_customer_id=customer,
    )

    assert ctx.customer_scope == frozenset({customer})
    assert ctx.custom_role_customer_id == customer
    assert ctx.agency_scope is None
    assert ctx.is_superadmin is False


async def test_superadmin_ignores_custom_role_scope():
    # A superadmin remains unbounded even if a custom-role customer is passed:
    # the superadmin branch short-circuits before custom-role handling.
    svc = _service(_FakeSession())
    ctx = await svc.build_tenant_context(
        _claims("superadmin"), custom_role_customer_id=uuid4()
    )
    assert ctx.is_superadmin is True
    assert ctx.customer_scope == frozenset()
    assert ctx.custom_role_customer_id is None


# ===========================================================================
# unknown role_type — fail-closed (Req 9.8)
# ===========================================================================


async def test_unknown_role_type_is_rejected():
    svc = _service(_FakeSession())
    with pytest.raises(TenantContextMissingError):
        await svc.build_tenant_context(_claims("wizard"))


# ===========================================================================
# impersonation — impersonated entity's boundary is enforced (Task 18.1,
# Req 12.1)
# ===========================================================================


class _Impersonation:
    """Minimal ``ImpersonationState`` stand-in (mirrors ImpersonationSession)."""

    def __init__(
        self,
        *,
        impersonated_agency_id: UUID | None = None,
        impersonated_customer_id: UUID | None = None,
        impersonator_user_id: UUID | None = None,
    ) -> None:
        self.impersonated_agency_id = impersonated_agency_id
        self.impersonated_customer_id = impersonated_customer_id
        self.impersonator_user_id = impersonator_user_id


async def test_impersonating_customer_collapses_scope_to_that_customer():
    # Req 12.1 — impersonating a Customer collapses scope to that single
    # Customer; impersonating flag and impersonated_customer_id are set.
    impersonator = uuid4()
    target_customer = uuid4()
    svc = _service(_FakeSession())

    ctx = await svc.build_tenant_context(
        _claims("agencyadmin", user_id=impersonator, agency_id=uuid4()),
        impersonation=_Impersonation(
            impersonated_customer_id=target_customer,
            impersonator_user_id=impersonator,
        ),
    )

    assert ctx.impersonating is True
    assert ctx.customer_scope == frozenset({target_customer})
    assert ctx.agency_scope is None
    assert ctx.impersonated_customer_id == target_customer
    assert ctx.impersonated_agency_id is None
    assert ctx.is_superadmin is False
    # The real acting user is recorded for audit; user_id stays the impersonator.
    assert ctx.impersonator_user_id == impersonator
    assert ctx.user_id == impersonator


async def test_superadmin_impersonating_customer_drops_to_customer_boundary():
    # Req 12.1 — even a superadmin drops to the impersonated boundary: the
    # impersonated scope is enforced, not the impersonator's unbounded scope.
    impersonator = uuid4()
    target_customer = uuid4()
    svc = _service(_FakeSession())

    ctx = await svc.build_tenant_context(
        _claims("superadmin", user_id=impersonator),
        impersonation=_Impersonation(
            impersonated_customer_id=target_customer,
            impersonator_user_id=impersonator,
        ),
    )

    assert ctx.is_superadmin is False
    assert ctx.impersonating is True
    assert ctx.customer_scope == frozenset({target_customer})
    assert ctx.impersonated_customer_id == target_customer
    assert ctx.impersonator_user_id == impersonator


async def test_impersonating_agency_scopes_to_agency_and_its_customers():
    # Req 12.1 — impersonating an Agency sets agency_scope and customer_scope to
    # that Agency's Customers (resolved via resolve_agency_customer_ids).
    impersonator = uuid4()
    target_agency = uuid4()
    other_agency = uuid4()
    c1, c2 = uuid4(), uuid4()
    session = _FakeSession(
        customers=[
            _customer(c1, target_agency),
            _customer(c2, target_agency),
            _customer(uuid4(), other_agency),  # excluded
        ]
    )
    svc = _service(session)

    ctx = await svc.build_tenant_context(
        _claims("superadmin", user_id=impersonator),
        impersonation=_Impersonation(
            impersonated_agency_id=target_agency,
            impersonator_user_id=impersonator,
        ),
    )

    assert ctx.impersonating is True
    assert ctx.agency_scope == target_agency
    assert ctx.customer_scope == frozenset({c1, c2})
    assert ctx.impersonated_agency_id == target_agency
    assert ctx.impersonated_customer_id is None
    assert ctx.is_superadmin is False
    assert ctx.impersonator_user_id == impersonator


async def test_impersonation_with_no_target_is_rejected():
    # Req 9.8 — an impersonation state with neither target cannot be scoped.
    svc = _service(_FakeSession())
    with pytest.raises(TenantContextMissingError):
        await svc.build_tenant_context(
            _claims("superadmin"),
            impersonation=_Impersonation(impersonator_user_id=uuid4()),
        )


async def test_no_impersonation_builds_own_context():
    # Req 12.4 — with no active impersonation (impersonation=None), the
    # impersonator's own role-based context is built unchanged.
    agency = uuid4()
    c1 = uuid4()
    session = _FakeSession(customers=[_customer(c1, agency)])
    svc = _service(session)

    ctx = await svc.build_tenant_context(
        _claims("agencyadmin", agency_id=agency),
        impersonation=None,
    )

    assert ctx.impersonating is False
    assert ctx.agency_scope == agency
    assert ctx.customer_scope == frozenset({c1})
    assert ctx.impersonated_customer_id is None
    assert ctx.impersonator_user_id is None

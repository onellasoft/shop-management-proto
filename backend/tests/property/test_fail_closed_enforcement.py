"""Property-based test for fail-closed per-action enforcement.

# Feature: onella-backend, Property 10: No action executes without a valid permission (fail-closed)

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 5.3**

Requirement 6.1 requires the Authorization_Service to read the Permission from
the database on the same request before executing an Action. Requirement 6.2
requires a request without the Permission to be rejected (no execution). Req 6.3
requires that a Permission that cannot be read is denied (fail-closed). Req 6.4
requires a revoked Permission to be denied on every subsequent enforced request
(modeled here by the grant simply not existing). Req 5.3 requires evaluation at
the granularity of a single Action.

Property 10 (design): *For any* ``(ctx, action_key)``:

* a superadmin is always permitted (``True``) — Req 4.2 bypass;
* a non-superadmin is permitted **iff** a grant row exists for that single
  Action (Req 5.3, 6.1) — so no grant means denied (Req 6.2, 6.4);
* when the database read raises, ``has_permission`` **never** returns ``True``
  — it raises :class:`NotAuthorizedError` (fail-closed, Req 6.3).

The database boundary is a tiny in-memory fake ``AsyncSession`` whose
``execute(...).scalar()`` returns the boolean the ``select(exists(grant))``
query yields. Grant existence is parameterized by Hypothesis; a separate
raising session exercises the fail-closed path. No real database is touched.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import NotAuthorizedError
from app.core.tenant_context import TenantContext
from app.services.authorization_service import AuthorizationService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _ScalarResult:
    """Result stub exposing ``.scalar()`` like a SQLAlchemy Result."""

    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _FakeSession:
    """AsyncSession stand-in returning a fixed ``exists()`` boolean.

    ``grant_exists`` is the value the ``select(exists(grant))`` query yields:
    ``True`` when some role assigned to the user grants the target Action,
    ``False`` otherwise.
    """

    def __init__(self, grant_exists: bool) -> None:
        self._grant_exists = grant_exists

    async def execute(self, _statement):  # noqa: ANN001
        return _ScalarResult(self._grant_exists)


class _RaisingSession:
    """AsyncSession stand-in that raises on read, to exercise fail-closed."""

    async def execute(self, _statement):  # noqa: ANN001
        raise SQLAlchemyError("boom")


def _ctx(
    *,
    is_superadmin: bool,
    custom_role_customer_id: uuid.UUID | None = None,
) -> TenantContext:
    """Build a minimal TenantContext for a permission check."""
    role_type = "superadmin" if is_superadmin else "customeradmin"
    return TenantContext(
        user_id=uuid.uuid4(),
        role_type=role_type,
        agency_scope=None,
        customer_scope=frozenset(),
        is_superadmin=is_superadmin,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=custom_role_customer_id,
    )


# A realistic module.submodule.resource.action shaped key.
_action_keys = st.builds(
    "{}.{}.{}.{}".format,
    st.sampled_from(["billing", "catalog", "orders", "users"]),
    st.sampled_from(["invoices", "products", "carts", "accounts"]),
    st.sampled_from(["invoice", "product", "cart", "account"]),
    st.sampled_from(["create", "read", "update", "delete"]),
)

_maybe_customer = st.one_of(st.none(), st.uuids())


# ---------------------------------------------------------------------------
# Superadmin bypass — always permitted, never touches the DB (Req 4.2)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(action_key=_action_keys, grant_exists=st.booleans())
async def test_superadmin_always_permitted(action_key, grant_exists):
    """A superadmin is permitted for any action regardless of grant rows."""
    svc = AuthorizationService(_FakeSession(grant_exists))
    assert await svc.has_permission(_ctx(is_superadmin=True), action_key) is True


# ---------------------------------------------------------------------------
# Non-superadmin — permitted iff a grant exists (Req 5.3, 6.1, 6.2, 6.4)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    action_key=_action_keys,
    grant_exists=st.booleans(),
    custom_role_customer_id=_maybe_customer,
)
async def test_non_superadmin_permitted_iff_grant_exists(
    action_key, grant_exists, custom_role_customer_id
):
    """has_permission returns exactly the grant-existence boolean."""
    svc = AuthorizationService(_FakeSession(grant_exists))
    ctx = _ctx(
        is_superadmin=False,
        custom_role_customer_id=custom_role_customer_id,
    )
    result = await svc.has_permission(ctx, action_key)
    # Permitted iff (superadmin OR grant exists); non-superadmin here, so it
    # tracks grant existence exactly (Req 5.3, 6.1, 6.2, 6.4).
    assert result is grant_exists


@settings(max_examples=100, deadline=None)
@given(action_key=_action_keys, custom_role_customer_id=_maybe_customer)
async def test_non_superadmin_without_grant_is_denied(
    action_key, custom_role_customer_id
):
    """No grant row means the action is denied (never executes) — Req 6.2/6.4."""
    svc = AuthorizationService(_FakeSession(False))
    ctx = _ctx(
        is_superadmin=False,
        custom_role_customer_id=custom_role_customer_id,
    )
    assert await svc.has_permission(ctx, action_key) is False


# ---------------------------------------------------------------------------
# Fail-closed — a DB read error never returns True; it raises (Req 6.3)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    action_key=_action_keys,
    is_superadmin=st.booleans(),
    custom_role_customer_id=_maybe_customer,
)
async def test_db_read_error_is_fail_closed(
    action_key, is_superadmin, custom_role_customer_id
):
    """When the grant read raises, has_permission raises — never returns True.

    A superadmin short-circuits before the read, so it stays permitted; every
    other principal fails closed with :class:`NotAuthorizedError` and the
    action must not execute (Req 6.3).
    """
    svc = AuthorizationService(_RaisingSession())
    ctx = _ctx(
        is_superadmin=is_superadmin,
        custom_role_customer_id=custom_role_customer_id,
    )

    if is_superadmin:
        # Superadmin never reaches the DB, so no error is raised.
        assert await svc.has_permission(ctx, action_key) is True
    else:
        with pytest.raises(NotAuthorizedError):
            await svc.has_permission(ctx, action_key)

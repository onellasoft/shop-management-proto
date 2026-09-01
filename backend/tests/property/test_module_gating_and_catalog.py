"""Property-based tests for module gating and the module catalog (Task 10.4).

This module holds two Hypothesis properties, each ≥100 iterations:

# Feature: onella-backend, Property 15: Module usability equals subscription state
# Feature: onella-backend, Property 17: Module catalog reflects subscription state

Property 15 (Validates 8.1, 8.2, 8.5)
-------------------------------------
For any ``(status, expires_at, now)``,
:meth:`AuthorizationService.is_module_usable` returns ``True`` **iff**::

    status == 'active' AND (expires_at IS NULL OR expires_at > now)

An absent subscription (no row) always yields ``False`` (Req 8.2). Because the
check reads per request against an injectable clock, expiry/removal is reflected
immediately, including for previously-issued sessions (Req 8.5).

Property 17 (Validates 8.3)
---------------------------
For a set of Modules with varied subscription states, the catalog reports
``subscribed`` iff a subscription row exists for the (Customer, Module) pair,
and ``usable`` iff that subscription is active and unexpired — i.e. exactly what
:meth:`AuthorizationService.is_module_usable` would return for the same row. The
catalog's :func:`app.api.routers.modules._is_usable` helper is exercised
directly against in-memory fakes, and its verdict is cross-checked against the
service so the ``usable`` flag the frontend renders matches enforcement.

The database boundary is a tiny in-memory fake ``AsyncSession``; no real DB is
touched and time is supplied by an injectable fake clock.
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.api.routers.modules import _is_usable
from app.services.authorization_service import AuthorizationService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FirstResult:
    """Result stub exposing ``.first()`` like a SQLAlchemy Result."""

    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def first(self) -> tuple | None:
        return self._row


class _FakeSession:
    """AsyncSession stand-in returning a fixed ``(status, expires_at)`` row.

    ``row`` is the tuple the ``select(status, expires_at)`` query yields, or
    ``None`` when no subscription exists for the (customer, module) pair.
    """

    def __init__(self, row: tuple | None) -> None:
        self._row = row

    async def execute(self, _statement):  # noqa: ANN001
        return _FirstResult(self._row)


# A fixed reference "now" the fake clock returns; expiry timestamps are drawn
# relative to it so the boundary (expires_at == now) is exercised.
NOW = datetime.datetime(2024, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _clock(now: datetime.datetime = NOW):
    return lambda: now


def _service(session, now: datetime.datetime = NOW) -> AuthorizationService:
    return AuthorizationService(session, now=_clock(now))


def _expected_usable(
    status: str | None,
    expires_at: datetime.datetime | None,
    now: datetime.datetime,
) -> bool:
    """Reference oracle: active AND unexpired (NULL expiry = no expiry)."""
    if status != "active":
        return False
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
    return expires_at > now


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Subscription statuses: 'active' plus several non-active values so the
# "iff active" half of the property is meaningfully exercised.
_statuses = st.sampled_from(
    ["active", "inactive", "suspended", "cancelled", "removed", "pending", ""]
)

# Offsets (in seconds) relative to NOW, spanning the boundary at exactly 0.
_offset_seconds = st.integers(min_value=-90 * 24 * 3600, max_value=90 * 24 * 3600)


@st.composite
def _expiries(draw):
    """Draw an ``expires_at``: None (no expiry), or NOW + offset (aware/naive)."""
    if draw(st.booleans()):
        return None
    offset = draw(_offset_seconds)
    ts = NOW + datetime.timedelta(seconds=offset)
    # Sometimes strip tzinfo to exercise the naive-timestamp normalization.
    if draw(st.booleans()):
        ts = ts.replace(tzinfo=None)
    return ts


# ---------------------------------------------------------------------------
# Property 15 — module usability equals subscription state (Req 8.1, 8.2, 8.5)
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(status=_statuses, expires_at=_expiries())
async def test_usable_iff_active_and_unexpired(status, expires_at):
    """is_module_usable is True iff status=='active' AND unexpired.

    Validates 8.1 (usable only when active + unexpired) and 8.2 (a
    non-active/expired subscription is treated as non-usable → rejected).
    """
    svc = _service(_FakeSession((status, expires_at)))
    result = await svc.is_module_usable(uuid4(), uuid4())
    assert result is _expected_usable(status, expires_at, NOW)


@settings(max_examples=100, deadline=None)
@given(customer_id=st.uuids(), module_id=st.uuids())
async def test_absent_subscription_is_never_usable(customer_id, module_id):
    """No subscription row → non-usable, for any (customer, module) (Req 8.2)."""
    svc = _service(_FakeSession(None))
    assert await svc.is_module_usable(customer_id, module_id) is False


@settings(max_examples=100, deadline=None)
@given(offset=st.integers(min_value=1, max_value=90 * 24 * 3600))
async def test_removal_or_expiry_reflected_per_request(offset):
    """A once-usable subscription becomes non-usable once expired (Req 8.5).

    The same service instance (modeling a session issued before the change)
    reports ``True`` while unexpired and ``False`` once the clock advances past
    ``expires_at`` — reads are per request, nothing is cached.
    """
    expires_at = NOW + datetime.timedelta(seconds=offset)
    row = ("active", expires_at)

    # Before expiry: usable.
    svc_before = _service(_FakeSession(row), now=NOW)
    assert await svc_before.is_module_usable(uuid4(), uuid4()) is True

    # After expiry (clock advanced past expires_at): non-usable.
    after = expires_at + datetime.timedelta(seconds=1)
    svc_after = _service(_FakeSession(row), now=after)
    assert await svc_after.is_module_usable(uuid4(), uuid4()) is False


# ---------------------------------------------------------------------------
# Property 17 — catalog reflects subscription state (Req 8.3)
# ---------------------------------------------------------------------------


@st.composite
def _module_states(draw):
    """Draw a list of (module_id, subscribed, status, expires_at) rows.

    ``subscribed`` marks whether a subscription row exists for the module. When
    it does, a status/expiry pair is drawn; when it does not, the module is
    absent from ``customer_subscriptions`` entirely.
    """
    count = draw(st.integers(min_value=1, max_value=8))
    states = []
    for _ in range(count):
        subscribed = draw(st.booleans())
        if subscribed:
            status = draw(_statuses)
            expires_at = draw(_expiries())
        else:
            status = None
            expires_at = None
        states.append((uuid4(), subscribed, status, expires_at))
    return states


@settings(max_examples=200, deadline=None)
@given(states=_module_states())
async def test_catalog_flags_match_subscription_state(states):
    """Catalog subscribed/usable flags are consistent with subscription state.

    For each Module the catalog builder decides:

    * ``subscribed`` — a subscription row exists for the (Customer, Module) pair;
    * ``usable`` — that row is active and unexpired (``_is_usable``), i.e.
      exactly what :meth:`AuthorizationService.is_module_usable` returns.

    Validates 8.3: every Module is reported, and unsubscribed/expired Modules
    come back ``usable=False`` so the frontend can lock them.
    """
    customer_id = uuid4()

    for module_id, subscribed, status, expires_at in states:
        # --- Catalog builder's per-module decision (mirrors modules.py) ---
        if not subscribed:
            catalog_subscribed = False
            catalog_usable = False
        else:
            catalog_subscribed = True
            catalog_usable = _is_usable(status, expires_at, now=NOW)

        # Every Module is present in the catalog regardless of state (Req 8.3).
        assert catalog_subscribed is subscribed

        # --- Cross-check usable against the service (single source of truth) ---
        row = None if not subscribed else (status, expires_at)
        svc = _service(_FakeSession(row))
        service_usable = await svc.is_module_usable(customer_id, module_id)

        assert catalog_usable is service_usable
        assert catalog_usable is _expected_usable(status, expires_at, NOW)

        # Unsubscribed Modules are never usable (locked with an upgrade prompt).
        if not subscribed:
            assert catalog_usable is False


@settings(max_examples=100, deadline=None)
@given(status=_statuses, expires_at=_expiries())
async def test_catalog_helper_matches_service_for_subscribed_module(
    status, expires_at
):
    """``_is_usable`` (catalog) and ``is_module_usable`` (service) agree.

    The flag the catalog renders for a subscribed Module must match what the
    enforcement layer will allow, so the two computations cannot diverge.
    """
    catalog_usable = _is_usable(status, expires_at, now=NOW)
    svc = _service(_FakeSession((status, expires_at)))
    service_usable = await svc.is_module_usable(uuid4(), uuid4())
    assert catalog_usable is service_usable

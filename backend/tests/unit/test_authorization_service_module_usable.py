"""Unit tests for AuthorizationService.is_module_usable (Task 10.2).

Requirement 8.1: THE Authorization_Service SHALL treat a Customer's SubModules,
Resources, and Actions as usable only when the parent Module is present and
unexpired in the Customer's Module_Subscriptions.

Requirement 8.2: IF a request attempts an Action whose Module is not present, or
is expired, in the Customer's Module_Subscriptions, THEN THE Authorization_Service
SHALL reject the request (the enforcement dependency raises
``module_not_subscribed`` when this check returns ``False``).

Requirement 8.4: WHEN a Module is added to a Customer's Module_Subscriptions, THE
Authorization_Service SHALL make that Module usable — modeled here by an active,
unexpired subscription row yielding ``True``.

Requirement 8.5: because the check reads per request and nothing is cached, a
removal/expiry is reflected on the very next request, including for previously
issued Access_Token sessions — modeled here by the same service instance
returning ``False`` once the subscription row is absent/expired.

These are pure-logic tests: the database boundary is a tiny in-memory fake
``AsyncSession`` whose ``execute(...).first()`` returns the ``(status,
expires_at)`` tuple selected by the query (or ``None`` for an absent row). Time
is supplied by an injectable fake clock so expiry is deterministic.
"""

from __future__ import annotations

import datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services.authorization_service import AuthorizationService

pytestmark = pytest.mark.asyncio


NOW = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _clock(now: datetime.datetime = NOW):
    return lambda: now


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


class _RaisingSession:
    """AsyncSession stand-in that raises on read, to exercise fail-closed."""

    async def execute(self, _statement):  # noqa: ANN001
        raise SQLAlchemyError("boom")


def _service(session, now: datetime.datetime = NOW) -> AuthorizationService:
    return AuthorizationService(session, now=_clock(now))


# ---------------------------------------------------------------------------
# Req 8.1 / 8.4 — active + unexpired subscription is usable
# ---------------------------------------------------------------------------


async def test_active_unexpired_subscription_is_usable():
    future = NOW + datetime.timedelta(days=30)
    svc = _service(_FakeSession(("active", future)))
    assert await svc.is_module_usable(uuid4(), uuid4()) is True


async def test_active_subscription_with_null_expiry_is_usable():
    # NULL expires_at means "no expiry" -> usable while active (Req 8.1).
    svc = _service(_FakeSession(("active", None)))
    assert await svc.is_module_usable(uuid4(), uuid4()) is True


# ---------------------------------------------------------------------------
# Req 8.1 / 8.2 / 8.5 — expired or absent subscription is non-usable
# ---------------------------------------------------------------------------


async def test_active_but_expired_subscription_is_not_usable():
    past = NOW - datetime.timedelta(seconds=1)
    svc = _service(_FakeSession(("active", past)))
    assert await svc.is_module_usable(uuid4(), uuid4()) is False


async def test_expiry_exactly_now_is_not_usable():
    # Usable requires expires_at strictly greater than now; equality expires.
    svc = _service(_FakeSession(("active", NOW)))
    assert await svc.is_module_usable(uuid4(), uuid4()) is False


async def test_absent_subscription_is_not_usable():
    # No row -> module not present in subscriptions -> non-usable (Req 8.2).
    svc = _service(_FakeSession(None))
    assert await svc.is_module_usable(uuid4(), uuid4()) is False


@pytest.mark.parametrize("status", ["inactive", "suspended", "cancelled", ""])
async def test_non_active_status_is_not_usable(status):
    future = NOW + datetime.timedelta(days=30)
    svc = _service(_FakeSession((status, future)))
    assert await svc.is_module_usable(uuid4(), uuid4()) is False


# ---------------------------------------------------------------------------
# Naive (tz-less) stored timestamps are normalized to UTC, not crashed on
# ---------------------------------------------------------------------------


async def test_naive_future_expiry_is_treated_as_utc_and_usable():
    naive_future = (NOW + datetime.timedelta(days=1)).replace(tzinfo=None)
    svc = _service(_FakeSession(("active", naive_future)))
    assert await svc.is_module_usable(uuid4(), uuid4()) is True


async def test_naive_past_expiry_is_treated_as_utc_and_not_usable():
    naive_past = (NOW - datetime.timedelta(days=1)).replace(tzinfo=None)
    svc = _service(_FakeSession(("active", naive_past)))
    assert await svc.is_module_usable(uuid4(), uuid4()) is False


# ---------------------------------------------------------------------------
# Fail-closed — an unreadable subscription is treated as non-usable (Req 8.2)
# ---------------------------------------------------------------------------


async def test_db_read_error_is_fail_closed():
    svc = _service(_RaisingSession())
    assert await svc.is_module_usable(uuid4(), uuid4()) is False


# ---------------------------------------------------------------------------
# Unresolved ids fail closed rather than granting access
# ---------------------------------------------------------------------------


async def test_none_module_id_is_not_usable():
    svc = _service(_FakeSession(("active", None)))
    assert await svc.is_module_usable(uuid4(), None) is False


async def test_none_customer_id_is_not_usable():
    svc = _service(_FakeSession(("active", None)))
    assert await svc.is_module_usable(None, uuid4()) is False

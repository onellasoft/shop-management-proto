"""Unit tests for agency customer-list cache invalidation (Task 15.2 — Req 10.4, 10.5).

Cover the invalidation wired in ``app.cache.customer_cache_invalidation`` and
the ``AuthorizationService.invalidate_agency_customer_cache`` entry point:

* 10.4 — the cached accessible-customer list for an Agency is invalidated when
  a Customer is **added / removed / suspended / activated** within it. Verified
  three ways: the service method, the explicit lifecycle helpers, and the
  SQLAlchemy flush/commit detection + dispatch.
* 10.5 — after invalidation the next ``resolve_agency_customer_ids`` reloads
  from the database and re-stores (the store-on-miss path from Task 15.1).

Redis is replaced with the in-memory ``_InMemoryCustomerListBackend`` fake and
the DB with the ``_CountingSession`` fake — the same doubles as
``test_customer_list_cache`` — so nothing about the cache rules is mocked and no
live server is required. The ORM event listeners are exercised against a
lightweight ``_FakeOrmSession`` (exposing ``new`` / ``deleted`` / ``dirty`` /
``info``) with ``status`` attribute history stubbed, so detection is verified
without a live Postgres database (the models use Postgres-specific types).
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from app.cache import customer_cache_invalidation as cci
from app.cache.customer_cache_invalidation import (
    collect_affected_agency_ids,
    invalidate_agency_customer_cache,
    on_customer_activated,
    on_customer_added,
    on_customer_removed,
    on_customer_suspended,
    set_cache_invalidation_scheduler,
)
from app.cache.customer_list_cache import AgencyCustomerListCache
from app.models.customer import Customer
from app.services.authorization_service import AuthorizationService


# ---------------------------------------------------------------------------
# Test doubles (mirroring test_customer_list_cache)
# ---------------------------------------------------------------------------


class _InMemoryCustomerListBackend:
    """In-memory ``CustomerListBackend`` fake."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self.data[key] = value
        self.ttls[key] = ttl_seconds

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)
            self.ttls.pop(key, None)


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


class _CountingSession:
    """AsyncSession stand-in returning fixed customer ids and counting reads."""

    def __init__(self, customer_ids: list[UUID]) -> None:
        self._customer_ids = list(customer_ids)
        self.execute_count = 0

    async def execute(self, _statement):  # noqa: ANN001
        self.execute_count += 1
        return _Result(list(self._customer_ids))


class _FakeOrmSession:
    """Minimal stand-in for a SQLAlchemy ``Session`` used by the listeners.

    Exposes the ``new`` / ``deleted`` / ``dirty`` collections the detection
    reads and an ``info`` dict the flush/commit callbacks stash into.
    """

    def __init__(
        self,
        *,
        new: set | None = None,
        deleted: set | None = None,
        dirty: set | None = None,
    ) -> None:
        self.new = new or set()
        self.deleted = deleted or set()
        self.dirty = dirty or set()
        self.info: dict = {}


def _cache(backend: _InMemoryCustomerListBackend | None = None) -> AgencyCustomerListCache:
    return AgencyCustomerListCache(backend or _InMemoryCustomerListBackend())


def _customer(agency_id: UUID) -> Customer:
    """Build a detached ``Customer`` with an agency id (no session attached)."""
    return Customer(id=uuid4(), agency_id=agency_id, name="Acme", status="active")


@pytest.fixture(autouse=True)
def _restore_scheduler():
    """Always restore the default scheduler after a test overrides it."""
    yield
    set_cache_invalidation_scheduler(None)


# ===========================================================================
# Service method — invalidate_agency_customer_cache (Req 10.4, 10.5)
# ===========================================================================


async def test_service_invalidate_deletes_agency_key_and_next_resolve_reloads():
    agency = uuid4()
    ids = [uuid4(), uuid4()]
    session = _CountingSession(ids)
    backend = _InMemoryCustomerListBackend()
    svc = AuthorizationService(session, customer_list_cache=_cache(backend))

    # Warm the cache via a first resolve (miss → 1 DB read + store).
    await svc.resolve_agency_customer_ids(agency)
    assert session.execute_count == 1
    assert f"agency:{agency}:customers" in backend.data

    # Invalidate → the agency key is gone (Req 10.4).
    await svc.invalidate_agency_customer_cache(agency)
    assert f"agency:{agency}:customers" not in backend.data

    # Next resolve is a miss → DB re-read and re-stored (Req 10.5).
    result = await svc.resolve_agency_customer_ids(agency)
    assert session.execute_count == 2
    assert set(result) == set(ids)
    assert json.loads(backend.data[f"agency:{agency}:customers"]) == [
        str(i) for i in ids
    ]


async def test_service_invalidate_is_scoped_to_one_agency():
    a1, a2 = uuid4(), uuid4()
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    await cache.set(a1, [uuid4()])
    await cache.set(a2, [uuid4()])
    svc = AuthorizationService(_CountingSession([]), customer_list_cache=cache)

    await svc.invalidate_agency_customer_cache(a1)

    assert f"agency:{a1}:customers" not in backend.data
    assert f"agency:{a2}:customers" in backend.data  # untouched


# ===========================================================================
# Explicit lifecycle helpers (Req 10.4) — add / remove / suspend / activate
# ===========================================================================


@pytest.mark.parametrize(
    "helper",
    [on_customer_added, on_customer_removed, on_customer_suspended, on_customer_activated],
)
async def test_lifecycle_helper_invalidates_and_forces_reload(helper):
    agency = uuid4()
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    await cache.set(agency, [uuid4(), uuid4()])
    assert await cache.get(agency) is not None

    await helper(agency, cache=cache)

    # Key deleted → next resolve reloads from the DB loader (Req 10.4, 10.5).
    assert await cache.get(agency) is None
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return [uuid4()]

    await cache.resolve(agency, loader)
    assert calls == 1


async def test_invalidate_primitive_uses_injected_cache():
    agency = uuid4()
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    await cache.set(agency, [uuid4()])

    await invalidate_agency_customer_cache(agency, cache=cache)

    assert await cache.get(agency) is None


# ===========================================================================
# Flush-time detection — collect_affected_agency_ids (Req 10.4)
# ===========================================================================


def test_collect_detects_added_customer():
    agency = uuid4()
    session = _FakeOrmSession(new={_customer(agency)})
    assert collect_affected_agency_ids(session) == {agency}


def test_collect_detects_removed_customer():
    agency = uuid4()
    session = _FakeOrmSession(deleted={_customer(agency)})
    assert collect_affected_agency_ids(session) == {agency}


def test_collect_detects_status_change_customer(monkeypatch):
    # A dirty Customer whose ``status`` changed (suspend/activate) is detected.
    agency = uuid4()
    changed = _customer(agency)
    monkeypatch.setattr(cci, "_status_changed", lambda c: c is changed)
    session = _FakeOrmSession(dirty={changed})

    assert collect_affected_agency_ids(session) == {agency}


def test_collect_ignores_dirty_customer_without_status_change(monkeypatch):
    # A Customer edited on a non-status field must NOT churn the cache.
    agency = uuid4()
    unchanged = _customer(agency)
    monkeypatch.setattr(cci, "_status_changed", lambda c: False)
    session = _FakeOrmSession(dirty={unchanged})

    assert collect_affected_agency_ids(session) == set()


def test_collect_ignores_non_customer_objects():
    session = _FakeOrmSession(new={object()}, deleted={object()}, dirty={object()})
    assert collect_affected_agency_ids(session) == set()


def test_collect_unions_multiple_agencies():
    a1, a2 = uuid4(), uuid4()
    session = _FakeOrmSession(
        new={_customer(a1)},
        deleted={_customer(a2)},
    )
    assert collect_affected_agency_ids(session) == {a1, a2}


# ===========================================================================
# Post-commit dispatch — flush records, commit invalidates (Req 10.4, 10.5)
# ===========================================================================


def test_after_flush_records_and_after_commit_dispatches(monkeypatch):
    agency = uuid4()
    added = _customer(agency)
    session = _FakeOrmSession(new={added})

    # Capture what the scheduler would dispatch instead of touching a loop/Redis.
    dispatched: list = []

    def recorder(coro):
        dispatched.append(coro)
        coro.close()  # avoid "coroutine was never awaited" warnings

    set_cache_invalidation_scheduler(recorder)

    # Flush → agency recorded on session.info; no dispatch yet.
    cci._after_flush(session, None)
    assert session.info[cci._SESSION_INFO_KEY] == {agency}
    assert dispatched == []

    # Commit → recorded agencies dispatched and the record cleared (Req 10.4).
    cci._after_commit(session)
    assert len(dispatched) == 1
    assert cci._SESSION_INFO_KEY not in session.info


def test_after_flush_accumulates_across_multiple_flushes(monkeypatch):
    a1, a2 = uuid4(), uuid4()
    session = _FakeOrmSession(new={_customer(a1)})

    cci._after_flush(session, None)
    # Second flush touches a different agency; both must be retained.
    session.new = {_customer(a2)}
    cci._after_flush(session, None)

    assert session.info[cci._SESSION_INFO_KEY] == {a1, a2}


def test_after_rollback_drops_pending_invalidations():
    agency = uuid4()
    session = _FakeOrmSession(new={_customer(agency)})
    cci._after_flush(session, None)
    assert cci._SESSION_INFO_KEY in session.info

    cci._after_rollback(session)
    assert cci._SESSION_INFO_KEY not in session.info


def test_after_commit_noop_when_nothing_recorded():
    session = _FakeOrmSession()
    dispatched: list = []
    set_cache_invalidation_scheduler(lambda coro: (dispatched.append(coro), coro.close()))

    cci._after_commit(session)  # no flush recorded anything

    assert dispatched == []


async def test_dispatched_invalidation_coroutine_deletes_the_key():
    # End-to-end: the coroutine the scheduler receives, when awaited, deletes
    # the agency key so the next resolve reloads from DB (Req 10.4, 10.5).
    agency = uuid4()
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    await cache.set(agency, [uuid4()])

    captured: list = []
    set_cache_invalidation_scheduler(lambda coro: captured.append(coro))

    added = _customer(agency)
    session = _FakeOrmSession(new={added})
    cci._after_flush(session, None)
    # Dispatch with the fake cache so the coroutine targets our backend.
    cci._dispatch_invalidations(session.info[cci._SESSION_INFO_KEY], cache=cache)

    assert len(captured) == 1
    await captured[0]  # await the scheduled invalidation
    assert await cache.get(agency) is None

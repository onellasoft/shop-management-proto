"""Property-based test for agency customer-list cache consistency.

# Feature: onella-backend, Property 21: Agency customer-list cache consistency

**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5**

Exercises the REAL cache + service implemented in Tasks 15.1/15.2 over
Hypothesis-generated worlds:

* ``app.cache.customer_list_cache.AgencyCustomerListCache`` — the get/set/
  resolve/invalidate primitives, the ``agency:{id}:customers`` key, and the
  24h TTL sourced from ``settings.agency_customer_cache_ttl_seconds``.
* ``app.services.authorization_service.AuthorizationService`` — the
  cache-backed ``resolve_agency_customer_ids`` (store-on-miss / hit-serves-
  from-cache) and ``invalidate_agency_customer_cache``.
* ``app.cache.customer_cache_invalidation`` — the lifecycle helpers
  (``on_customer_added/removed/suspended/activated``) that funnel into the same
  invalidation primitive.

The property drives a sequence of operations (resolve / add / remove / suspend
/ activate) against an authoritative in-memory "database" set per agency and
asserts the following invariants hold across every generated world:

1. **Store-on-miss + TTL** (Req 10.1, 10.3): after a resolve on a cold key, the
   agency key exists with a stored TTL equal to the 24h config value and the
   cached value equals the DB-loaded id set.
2. **Hit serves from cache** (Req 10.2): with a warm, unexpired entry, resolve
   returns the cached list WITHOUT invoking the DB loader (loader call count
   unchanged).
3. **Invalidation → reload reflects current DB** (Req 10.4, 10.5): after any
   lifecycle event triggers invalidation, the key is gone and the NEXT resolve
   reloads from the DB and returns the CURRENT authoritative state — the cache
   never serves stale data across an invalidation boundary.

The DB is modelled as a mutable in-memory authoritative set of customer ids the
generated add/remove operations mutate; the cache loader reads from that set,
so a post-invalidation reload faithfully reflects the mutations. Redis is
replaced with the same in-memory ``CustomerListBackend`` fake used by the unit
tests (nothing about the cache rules is mocked, no live server required). The
5-second invalidation bound is satisfied structurally: the lifecycle helpers /
service invalidation delete the key synchronously in-process, so asserting the
key is gone immediately after the helper is a faithful check.

Because the cache/service APIs are ``async`` and Hypothesis drives synchronous
test bodies, each example runs the scenario coroutine to completion via
``asyncio.run``; the fakes perform no real I/O, so 100+ iterations stay fast.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from app.cache.customer_cache_invalidation import (
    on_customer_activated,
    on_customer_added,
    on_customer_removed,
    on_customer_suspended,
)
from app.cache.customer_list_cache import AgencyCustomerListCache
from app.core.config import settings as app_settings
from app.services.authorization_service import AuthorizationService


# ---------------------------------------------------------------------------
# Test doubles (mirroring tests/unit/test_customer_list_cache.py)
# ---------------------------------------------------------------------------


class _InMemoryCustomerListBackend:
    """In-memory ``CustomerListBackend`` fake recording set TTLs.

    Implements the async key/value protocol the cache depends on. TTL expiry is
    not time-driven; the scenario simulates a miss/expiry only via ``delete``
    (invalidation), matching the in-process behaviour under test.
    """

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


class _MutableDbSession:
    """AsyncSession stand-in backed by a mutable authoritative customer set.

    Unlike the unit-test ``_CountingSession`` (which returns a fixed list), this
    fake reads the CURRENT authoritative set on every ``execute`` so a resolve
    after an add/remove reflects the mutation — exactly what a real DB reload
    after cache invalidation would return. ``execute_count`` records the number
    of DB reads so the property can assert the loader is skipped on a cache hit
    and invoked on a miss.
    """

    def __init__(self, db: set[UUID]) -> None:
        self._db = db
        self.execute_count = 0

    async def execute(self, _statement):  # noqa: ANN001
        self.execute_count += 1
        # The service issues select(Customer.id).where(agency_id == ...); the
        # scenario runs one agency at a time, so the authoritative set is the
        # answer. Snapshot it so later mutations don't alias the returned rows.
        return _Result(list(self._db))


def _cache(backend: _InMemoryCustomerListBackend) -> AgencyCustomerListCache:
    return AgencyCustomerListCache(backend)


# ---------------------------------------------------------------------------
# Operation model
# ---------------------------------------------------------------------------
#
# Each generated world is: one agency, an initial authoritative customer set,
# and a sequence of operations. Operations are one of:
#   ("resolve",)                    — resolve the accessible customer list
#   ("add", customer_id)            — add a customer + invalidate (Req 10.4)
#   ("remove", customer_id)         — remove a customer + invalidate (Req 10.4)
#   ("suspend",)                    — a status change + invalidate (Req 10.4)
#   ("activate",)                   — a status change + invalidate (Req 10.4)
#
# add/remove mutate the authoritative DB set; all four lifecycle ops invalidate
# via the real lifecycle helpers. "resolve" checks the store-on-miss/hit/reload
# invariants against the authoritative set.

_uuids = st.builds(uuid4)


@st.composite
def _world(draw: st.DrawFn):
    """A single agency, its initial customer set, and an operation sequence."""
    agency = draw(_uuids)
    # A pool of candidate customer ids the operations draw from, so add/remove
    # can target ids that plausibly exist (or not).
    pool = draw(st.lists(_uuids, min_size=1, max_size=8, unique=True))
    initial = set(draw(st.sets(st.sampled_from(pool), max_size=len(pool))))

    # Build a variable-length op sequence; ops that mutate membership carry a
    # customer id drawn from the pool. "resolve" is weighted so most worlds
    # exercise several read checks between mutations.
    op_kinds = draw(
        st.lists(
            st.sampled_from(
                ["resolve", "resolve", "add", "remove", "suspend", "activate"]
            ),
            min_size=1,
            max_size=12,
        )
    )
    operations: list[tuple] = []
    for kind in op_kinds:
        if kind in ("add", "remove"):
            operations.append((kind, draw(st.sampled_from(pool))))
        else:
            operations.append((kind,))
    return agency, initial, operations


async def _lifecycle_invalidate(kind: str, agency: UUID, cache: AgencyCustomerListCache) -> None:
    """Route to the REAL lifecycle helper for ``kind`` (Req 10.4)."""
    helper = {
        "add": on_customer_added,
        "remove": on_customer_removed,
        "suspend": on_customer_suspended,
        "activate": on_customer_activated,
    }[kind]
    await helper(agency, cache=cache)


async def _run_scenario(agency: UUID, initial: set[UUID], operations: list[tuple]) -> None:
    """Drive the operation sequence, asserting Property 21 at each step."""
    key = f"agency:{agency}:customers"
    ttl_expected = app_settings.agency_customer_cache_ttl_seconds

    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    db: set[UUID] = set(initial)
    session = _MutableDbSession(db)
    svc = AuthorizationService(session, customer_list_cache=cache)

    for op in operations:
        kind = op[0]

        if kind == "resolve":
            key_present_before = key in backend.data
            reads_before = session.execute_count

            result = await svc.resolve_agency_customer_ids(agency)

            # The resolved list always matches the current authoritative DB set.
            assert set(result) == db

            if key_present_before:
                # Invariant 2 — hit serves from cache without a DB read (Req 10.2).
                assert session.execute_count == reads_before
            else:
                # Invariant 1 — store-on-miss: exactly one DB read happened,
                # the key now exists with the 24h TTL, and the cached value
                # equals the DB-loaded set (Req 10.1, 10.3).
                assert session.execute_count == reads_before + 1
                assert key in backend.data
                assert backend.ttls[key] == ttl_expected
                assert ttl_expected <= 24 * 60 * 60  # TTL no greater than 24h
                cached = {UUID(s) for s in json.loads(backend.data[key])}
                assert cached == db
            continue

        # Lifecycle operation: mutate the authoritative DB (for add/remove),
        # then invalidate via the real lifecycle helper (Req 10.4).
        if kind == "add":
            db.add(op[1])
        elif kind == "remove":
            db.discard(op[1])
        # suspend / activate are status transitions: they do not change
        # membership of the id set here, but they DO invalidate the cache.

        await _lifecycle_invalidate(kind, agency, cache)

        # Invariant 3 (part a) — invalidation deletes the key within the 5s
        # bound; the helper runs synchronously in-process so the delete has
        # already landed (Req 10.4).
        assert key not in backend.data

        # Invariant 3 (part b) — the NEXT resolve reloads from the DB and
        # reflects the CURRENT authoritative state; no stale data crosses the
        # invalidation boundary (Req 10.5).
        reads_before = session.execute_count
        reloaded = await svc.resolve_agency_customer_ids(agency)
        assert session.execute_count == reads_before + 1  # forced DB reload
        assert set(reloaded) == db
        cached = {UUID(s) for s in json.loads(backend.data[key])}
        assert cached == db


# ===========================================================================
# Property 21 — Agency customer-list cache consistency
# ===========================================================================


# Feature: onella-backend, Property 21: Agency customer-list cache consistency
@settings(max_examples=200, deadline=None)
@given(world=_world())
def test_agency_customer_list_cache_consistency(world) -> None:
    """Store-on-miss + TTL, hit-serves-from-cache, and invalidate-then-reload
    all hold across generated resolve/mutate/invalidate sequences.

    Validates Requirements 10.1, 10.2, 10.3, 10.4, 10.5.
    """
    agency, initial, operations = world
    asyncio.run(_run_scenario(agency, initial, operations))

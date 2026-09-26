"""Unit tests for the agency customer-list cache (Task 15.1 — Requirement 10).

Cover the Redis-backed cache in ``app.cache.customer_list_cache`` and its
integration into ``AuthorizationService.resolve_agency_customer_ids``:

* 10.1 — ``set`` stores the customer-id list under ``agency:{id}:customers``
  with the 24h TTL; ``resolve`` stores the DB-loaded list on a miss.
* 10.2 — ``get``/``resolve`` return the cached list on a hit without hitting
  the DB loader.
* 10.3 — ``get`` on a cold key returns ``None``; ``resolve`` on a miss loads
  from the DB and caches the result.

Redis is replaced with an in-memory ``CustomerListBackend`` fake implementing
the same async protocol, so nothing about the cache rules is mocked and no live
server is required. The AuthorizationService integration uses the same
``_FakeSession`` pattern as ``test_authorization_service_build_context`` for the
database loader.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from app.cache.customer_list_cache import (
    AgencyCustomerListCache,
    RedisCustomerListBackend,
)
from app.core.config import settings
from app.core.security import ACCESS_TOKEN_TYPE, AccessTokenClaims
from app.models.customer import Customer
from app.services.authorization_service import AuthorizationService


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _InMemoryCustomerListBackend:
    """In-memory ``CustomerListBackend`` fake recording set TTLs.

    Implements the async key/value protocol the cache depends on. TTL expiry is
    not time-driven; tests simulate a miss/expiry by clearing the store.
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


class _CountingSession:
    """AsyncSession stand-in returning fixed customer ids and counting reads.

    ``execute_count`` records how many times the DB was queried so tests can
    assert the loader is called exactly once on a miss and never on a hit.
    """

    def __init__(self, customer_ids: list[UUID]) -> None:
        self._customer_ids = list(customer_ids)
        self.execute_count = 0

    async def execute(self, _statement):  # noqa: ANN001
        self.execute_count += 1
        return _Result(list(self._customer_ids))


def _cache(backend: _InMemoryCustomerListBackend | None = None):
    return AgencyCustomerListCache(backend or _InMemoryCustomerListBackend())


def _agencyadmin_claims(agency_id: UUID) -> AccessTokenClaims:
    return AccessTokenClaims(
        sub=uuid4(),
        email="agency@example.com",
        role_type="agencyadmin",
        agency_id=agency_id,
        customer_id=None,
        iat=0,
        exp=0,
        token_type=ACCESS_TOKEN_TYPE,
    )


# ===========================================================================
# Cache module — set/get round-trip (Req 10.1, 10.2)
# ===========================================================================


async def test_set_then_get_round_trips_customer_ids():
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    agency = uuid4()
    ids = [uuid4(), uuid4(), uuid4()]

    await cache.set(agency, ids)
    got = await cache.get(agency)

    assert got == ids


async def test_set_stores_json_array_under_agency_key_with_24h_ttl():
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    agency = uuid4()
    ids = [uuid4(), uuid4()]

    await cache.set(agency, ids)

    key = f"agency:{agency}:customers"
    assert key in backend.data
    # Value is a JSON array of id strings (Req 10.1).
    assert json.loads(backend.data[key]) == [str(i) for i in ids]
    # TTL is 24 hours, sourced from config (Req 10.1).
    assert backend.ttls[key] == settings.agency_customer_cache_ttl_seconds
    assert backend.ttls[key] == 86_400


# ===========================================================================
# Cache module — cold key miss returns None (Req 10.3)
# ===========================================================================


async def test_get_on_cold_key_returns_none():
    cache = _cache()
    assert await cache.get(uuid4()) is None


async def test_get_on_corrupt_payload_returns_none():
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    agency = uuid4()
    backend.data[f"agency:{agency}:customers"] = "not-json"

    assert await cache.get(agency) is None


# ===========================================================================
# Cache module — resolve store-on-miss / hit (Req 10.2, 10.3)
# ===========================================================================


async def test_resolve_on_miss_calls_loader_once_and_caches():
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    agency = uuid4()
    ids = [uuid4(), uuid4()]
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return ids

    first = await cache.resolve(agency, loader)
    assert first == ids
    assert calls == 1  # loader invoked on the miss (Req 10.3)

    # Second resolve is a hit → loader not called again (Req 10.2).
    second = await cache.resolve(agency, loader)
    assert second == ids
    assert calls == 1


async def test_resolve_on_hit_does_not_call_loader():
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    agency = uuid4()
    ids = [uuid4()]
    await cache.set(agency, ids)

    async def loader():
        raise AssertionError("loader must not be called on a cache hit")

    assert await cache.resolve(agency, loader) == ids


async def test_invalidate_forces_next_resolve_to_reload():
    backend = _InMemoryCustomerListBackend()
    cache = _cache(backend)
    agency = uuid4()
    await cache.set(agency, [uuid4()])

    await cache.invalidate(agency)
    assert await cache.get(agency) is None


# ===========================================================================
# AuthorizationService integration — cache-backed resolution (Req 10.1–10.3)
# ===========================================================================


async def test_service_resolution_hits_cache_without_db_on_second_call():
    agency = uuid4()
    ids = [uuid4(), uuid4()]
    session = _CountingSession(ids)
    cache = _cache()
    svc = AuthorizationService(session, customer_list_cache=cache)

    # First call: cache miss → DB loader runs once and stores the result.
    first = await svc.resolve_agency_customer_ids(agency)
    assert set(first) == set(ids)
    assert session.execute_count == 1

    # Second call: cache hit → DB loader NOT called again (Req 10.2).
    second = await svc.resolve_agency_customer_ids(agency)
    assert set(second) == set(ids)
    assert session.execute_count == 1


async def test_service_falls_back_to_db_and_stores_on_miss():
    agency = uuid4()
    ids = [uuid4()]
    session = _CountingSession(ids)
    backend = _InMemoryCustomerListBackend()
    svc = AuthorizationService(session, customer_list_cache=_cache(backend))

    result = await svc.resolve_agency_customer_ids(agency)

    # DB queried once (miss) and result cached under the agency key (Req 10.3).
    assert session.execute_count == 1
    assert set(result) == set(ids)
    key = f"agency:{agency}:customers"
    assert json.loads(backend.data[key]) == [str(i) for i in ids]


async def test_build_tenant_context_uses_cache_for_agencyadmin_scope():
    # The agencyadmin scope derivation resolves customer ids via the cache:
    # a warm cache means the DB is not queried during context build (Req 10.2).
    agency = uuid4()
    c1, c2 = uuid4(), uuid4()
    session = _CountingSession([c1, c2])
    cache = _cache()
    svc = AuthorizationService(session, customer_list_cache=cache)

    # Warm the cache directly.
    await cache.set(agency, [c1, c2])

    ctx = await svc.build_tenant_context(_agencyadmin_claims(agency))

    assert ctx.agency_scope == agency
    assert ctx.customer_scope == frozenset({c1, c2})
    assert session.execute_count == 0  # served from cache, no DB read


# ===========================================================================
# Redis backend delegates to the shared client (smoke, no live server)
# ===========================================================================


class _RecordingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):  # noqa: ANN001
        self.calls.append(("set", key, value, ex))
        self.store[key] = value

    async def get(self, key):  # noqa: ANN001
        self.calls.append(("get", key))
        return self.store.get(key)

    async def delete(self, *keys):  # noqa: ANN001
        self.calls.append(("delete", keys))
        for k in keys:
            self.store.pop(k, None)


async def test_redis_backend_passes_ttl_via_ex():
    redis = _RecordingRedis()
    backend = RedisCustomerListBackend(redis)  # type: ignore[arg-type]

    await backend.set_with_ttl("k", "v", 86_400)

    assert ("set", "k", "v", 86_400) in redis.calls
    assert await backend.get("k") == "v"

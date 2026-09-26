"""Agency accessible-customer-list cache backed by Redis (Requirement 10).

Caches, per Agency, the list of Customer ids the Agency can access so that
agencyadmin tenant-context derivation (Task 13.1) stays performant without
re-querying Postgres on every request.

- Cache key: ``agency:{agency_id}:customers`` (per the design).
- Value: a JSON array of customer id strings.
- TTL: 24 hours, sourced from ``settings.agency_customer_cache_ttl_seconds``
  (mirrors the OTP TTL convention in ``app.core.config``).

Behavior (Req 10.1, 10.2, 10.3):

- :meth:`AgencyCustomerListCache.set` stores the JSON list with the 24h TTL
  (Req 10.1).
- :meth:`AgencyCustomerListCache.get` returns the cached list on a hit
  (Req 10.2) or ``None`` on a miss / expired key (the store-on-miss reload is
  the caller's responsibility — see :meth:`resolve`).
- :meth:`AgencyCustomerListCache.resolve` combines the two: on a hit it returns
  the cached list; on a miss it invokes the supplied ``db_loader`` and stores
  the result with the 24h TTL before returning it (Req 10.3, store-on-miss).

Cache **invalidation** on customer lifecycle changes (add/remove/suspend/
activate) is Task 15.2 and is intentionally *not* wired here; the trivial
:meth:`invalidate` primitive is provided so 15.2 only has to call it from the
relevant lifecycle events.

Redis access follows the conventions in ``app.cache.otp_store``: the client is
sourced from ``app.cache.redis_client.get_redis`` and abstracted behind a small
protocol so tests can inject an in-memory fake instead of a live server.
``decode_responses=True`` on the shared client means values are ``str``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.cache.redis_client import Redis, get_redis
from app.core.config import settings

# ---------------------------------------------------------------------------
# Key namespace (design: "agency:{agency_id}:customers")
# ---------------------------------------------------------------------------
_CUSTOMERS_KEY = "agency:{agency_id}:customers"

#: Loader that resolves an agency's customer ids from the database on a miss.
DbLoader = Callable[[], Awaitable[Iterable[UUID]]]


def _key(agency_id: UUID) -> str:
    """Return the Redis key holding ``agency_id``'s customer-id list."""
    return _CUSTOMERS_KEY.format(agency_id=agency_id)


# ---------------------------------------------------------------------------
# Backend abstraction
# ---------------------------------------------------------------------------
@runtime_checkable
class CustomerListBackend(Protocol):
    """Minimal async key/value operations the customer-list cache depends on.

    Implemented by :class:`RedisCustomerListBackend` in production and by an
    in-memory fake in tests, so cache logic is verifiable without a live Redis.
    """

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        """Set ``key`` to ``value`` with an expiry of ``ttl_seconds``."""

    async def get(self, key: str) -> str | None:
        """Return the value for ``key`` or ``None`` if absent/expired."""

    async def delete(self, *keys: str) -> None:
        """Delete one or more keys (missing keys are ignored)."""


class RedisCustomerListBackend:
    """:class:`CustomerListBackend` backed by the shared async Redis client."""

    def __init__(self, client: Redis | None = None) -> None:
        self._client = client or get_redis()

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class AgencyCustomerListCache:
    """Redis-backed cache of an Agency's accessible customer-id list (Req 10)."""

    def __init__(
        self,
        backend: CustomerListBackend | None = None,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        self._backend: CustomerListBackend = backend or RedisCustomerListBackend()
        self._ttl_seconds = (
            ttl_seconds
            if ttl_seconds is not None
            else settings.agency_customer_cache_ttl_seconds
        )

    async def get(self, agency_id: UUID) -> list[UUID] | None:
        """Return the cached customer-id list for ``agency_id`` (Req 10.2).

        Returns the deserialized list of :class:`UUID` on a cache hit, or
        ``None`` on a miss/expired key. A malformed cached payload is treated as
        a miss (``None``) so a corrupt entry degrades to a DB reload rather than
        raising. Repopulation on a miss is the caller's responsibility
        (see :meth:`resolve`, Req 10.3).
        """
        raw = await self._backend.get(_key(agency_id))
        if raw is None:
            return None
        try:
            decoded = json.loads(raw)
            return [UUID(str(item)) for item in decoded]
        except (ValueError, TypeError):
            # Corrupt payload → treat as a miss so the caller reloads from DB.
            return None

    async def set(self, agency_id: UUID, customer_ids: Iterable[UUID]) -> None:
        """Store ``agency_id``'s customer-id list with a 24h TTL (Req 10.1).

        The ids are serialized as a JSON array of strings. Duplicates are
        preserved as given by the caller; ordering is not significant to the
        tenant-scope consumer (it builds a ``frozenset``).
        """
        payload = json.dumps([str(cid) for cid in customer_ids])
        await self._backend.set_with_ttl(
            _key(agency_id), payload, self._ttl_seconds
        )

    async def resolve(
        self, agency_id: UUID, db_loader: DbLoader
    ) -> list[UUID]:
        """Return ``agency_id``'s customer-id list, using cache with DB fallback.

        On a cache hit the cached list is returned without touching the database
        (Req 10.2). On a miss/expired key, ``db_loader`` is awaited to resolve
        the list from the database and the result is stored with the 24h TTL
        before being returned (Req 10.3, store-on-miss / Req 10.1).

        Parameters
        ----------
        agency_id:
            The Agency whose accessible customer list is being resolved.
        db_loader:
            An async, no-argument callable returning the authoritative customer
            ids from the database. Invoked only on a cache miss.

        Returns
        -------
        list[UUID]
            The resolved customer ids.
        """
        cached = await self.get(agency_id)
        if cached is not None:
            return cached
        loaded = list(await db_loader())
        await self.set(agency_id, loaded)
        return loaded

    async def invalidate(self, agency_id: UUID) -> None:
        """Delete the cached customer-id list for ``agency_id`` (Req 10.4, 10.5).

        Provided as the primitive Task 15.2 invokes from customer lifecycle
        events (add/remove/suspend/activate). After invalidation the next
        :meth:`resolve` repopulates from the database. The invocation on
        lifecycle events is out of scope for Task 15.1.
        """
        await self._backend.delete(_key(agency_id))


def get_agency_customer_list_cache() -> AgencyCustomerListCache:
    """Return an :class:`AgencyCustomerListCache` on the shared Redis client."""
    return AgencyCustomerListCache()


__all__ = [
    "AgencyCustomerListCache",
    "CustomerListBackend",
    "RedisCustomerListBackend",
    "get_agency_customer_list_cache",
    "DbLoader",
]

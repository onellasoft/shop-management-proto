"""Async Redis client factory / singleton.

Provides a process-wide ``redis.asyncio`` client used by the OTP store
(Req 2.1, 2.4, 2.6, 2.7), the agency customer-list cache (Req 10), and the
Celery broker. The connection URL is sourced from
``app.core.config.settings.redis_url``.

Design references:
- Technology Stack: "Redis — OTP storage (TTL), agency customer-list cache,
  Celery broker".

The client is created lazily on first use and cached for the lifetime of the
process. ``decode_responses=True`` is enabled so callers work with ``str``
values rather than ``bytes`` — the OTP store and cache treat values as text.
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.core.config import settings

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------
# A single async client is shared process-wide. ``redis.asyncio`` manages an
# internal connection pool, so a single client instance is the recommended
# usage pattern.
_client: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide async Redis client, creating it on first use.

    The client is configured from ``settings.redis_url`` and decodes responses
    to ``str``. Subsequent calls return the same instance.
    """
    global _client
    if _client is None:
        _client = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


async def close_redis() -> None:
    """Close the shared client and release its connection pool.

    Intended for application shutdown / test teardown. After closing, a
    subsequent :func:`get_redis` call creates a fresh client.
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


__all__ = ["get_redis", "close_redis", "Redis"]

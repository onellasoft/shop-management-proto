"""OTP store backed by Redis (mobile-number / OTP authentication).

Encapsulates every OTP-related side effect required by Requirement 2 so the
Auth_Service can drive the OTP lifecycle without touching Redis directly:

- Generate a six-digit OTP and store it with a 10-minute (600s) TTL (Req 2.1).
- Rate-limit OTP requests to at most 3 per rolling 10-minute window (Req 2.4).
- Count failed verification attempts and invalidate the OTP after 5 (Req 2.6, 2.7).
- Invalidate the stored OTP so it cannot be reused (Req 2.9).

Redis access is abstracted behind the :class:`OTPBackend` protocol. The
default :class:`RedisOTPBackend` talks to the shared async client, while tests
may inject an in-memory fake implementing the same protocol (see the property
tests for the OTP lifecycle). Nothing in this module imports Redis eagerly at
call time beyond the injected backend, keeping the store fully substitutable.
"""

from __future__ import annotations

import secrets
from typing import Protocol, runtime_checkable

from app.cache.redis_client import Redis, get_redis
from app.core.config import settings

# ---------------------------------------------------------------------------
# Constants (Req 2.1, 2.4, 2.6, 2.7)
# ---------------------------------------------------------------------------
OTP_DIGITS = 6
#: Max failed verification attempts before the stored OTP is invalidated (Req 2.7).
MAX_FAILED_ATTEMPTS = 5
#: Max OTP requests permitted within the rate-limit window (Req 2.4).
RATE_LIMIT_MAX_REQUESTS = 3
#: Rate-limit window in seconds: 10 minutes (Req 2.4).
RATE_LIMIT_WINDOW_SECONDS = 600

# Redis key namespaces. Values are stored per mobile number.
_OTP_KEY = "otp:code:{mobile}"
_FAILURE_KEY = "otp:failures:{mobile}"
_RATE_LIMIT_KEY = "otp:ratelimit:{mobile}"


def generate_otp() -> str:
    """Return a cryptographically-random zero-padded six-digit OTP (Req 2.1)."""
    return f"{secrets.randbelow(10 ** OTP_DIGITS):0{OTP_DIGITS}d}"


# ---------------------------------------------------------------------------
# Backend abstraction
# ---------------------------------------------------------------------------
@runtime_checkable
class OTPBackend(Protocol):
    """Minimal async key/value operations the OTP store depends on.

    Implemented by :class:`RedisOTPBackend` in production and by an in-memory
    fake in property tests, so OTP logic is verifiable without a live Redis.
    """

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        """Set ``key`` to ``value`` with an expiry of ``ttl_seconds``."""

    async def get(self, key: str) -> str | None:
        """Return the value for ``key`` or ``None`` if absent/expired."""

    async def delete(self, *keys: str) -> None:
        """Delete one or more keys (missing keys are ignored)."""

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        """Atomically increment ``key`` and set its TTL on first increment.

        Returns the counter value after incrementing. The TTL is applied when
        the counter is created (value becomes 1) so the window is anchored to
        the first event and does not slide on subsequent increments.
        """


class RedisOTPBackend:
    """:class:`OTPBackend` implementation backed by the shared async client."""

    def __init__(self, client: Redis | None = None) -> None:
        self._client = client or get_redis()

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        value = await self._client.incr(key)
        if value == 1:
            # First increment created the counter; anchor the window to now.
            await self._client.expire(key, ttl_seconds)
        return int(value)


# ---------------------------------------------------------------------------
# OTP store
# ---------------------------------------------------------------------------
class OTPStore:
    """OTP lifecycle operations over an :class:`OTPBackend` (Requirement 2)."""

    def __init__(
        self,
        backend: OTPBackend | None = None,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        self._backend: OTPBackend = backend or RedisOTPBackend()
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.otp_ttl_seconds

    # -- request side (Req 2.1, 2.4) ---------------------------------------
    async def store_otp(self, mobile: str) -> str:
        """Generate and store a six-digit OTP for ``mobile`` with a 10-min TTL.

        Resets any prior failure counter so a freshly issued OTP starts with a
        clean attempt count (Req 2.1, 2.6). Returns the generated OTP so the
        caller can dispatch it via the SMS sender.
        """
        otp = generate_otp()
        await self._backend.set_with_ttl(
            _OTP_KEY.format(mobile=mobile), otp, self._ttl_seconds
        )
        # New OTP → clear stale failure counter for the previous code.
        await self._backend.delete(_FAILURE_KEY.format(mobile=mobile))
        return otp

    async def get_otp(self, mobile: str) -> str | None:
        """Return the stored OTP for ``mobile`` or ``None`` if absent/expired.

        A ``None`` result covers both "never requested" and "expired" (Req 2.8);
        the TTL causes Redis to drop the key once the OTP expires.
        """
        return await self._backend.get(_OTP_KEY.format(mobile=mobile))

    async def increment_rate_limit(self, mobile: str) -> int:
        """Increment and return the OTP-request count in the 10-min window.

        Callers reject the request when the returned count exceeds
        :data:`RATE_LIMIT_MAX_REQUESTS` (Req 2.4). The window is anchored to the
        first request in the window.
        """
        return await self._backend.incr_with_ttl(
            _RATE_LIMIT_KEY.format(mobile=mobile), RATE_LIMIT_WINDOW_SECONDS
        )

    def is_rate_limited(self, request_count: int) -> bool:
        """Return ``True`` when ``request_count`` exceeds the allowed max (Req 2.4)."""
        return request_count > RATE_LIMIT_MAX_REQUESTS

    # -- verify side (Req 2.6, 2.7, 2.9) -----------------------------------
    async def increment_failure_count(self, mobile: str) -> int:
        """Increment failed-verification attempts; invalidate the OTP at 5.

        Returns the failure count after incrementing. When the count reaches
        :data:`MAX_FAILED_ATTEMPTS`, the stored OTP is invalidated so no further
        verification can succeed (Req 2.7). The failure counter shares the OTP's
        TTL window.
        """
        count = await self._backend.incr_with_ttl(
            _FAILURE_KEY.format(mobile=mobile), self._ttl_seconds
        )
        if count >= MAX_FAILED_ATTEMPTS:
            await self.invalidate(mobile)
        return count

    async def invalidate(self, mobile: str) -> None:
        """Remove the stored OTP and its failure counter for ``mobile``.

        Used both on successful verification (Req 2.9) and when the failure
        threshold is reached (Req 2.7), guaranteeing the OTP cannot be reused.
        """
        await self._backend.delete(
            _OTP_KEY.format(mobile=mobile),
            _FAILURE_KEY.format(mobile=mobile),
        )


def get_otp_store() -> OTPStore:
    """Return an :class:`OTPStore` backed by the shared async Redis client."""
    return OTPStore()


__all__ = [
    "OTPStore",
    "OTPBackend",
    "RedisOTPBackend",
    "get_otp_store",
    "generate_otp",
    "OTP_DIGITS",
    "MAX_FAILED_ATTEMPTS",
    "RATE_LIMIT_MAX_REQUESTS",
    "RATE_LIMIT_WINDOW_SECONDS",
]

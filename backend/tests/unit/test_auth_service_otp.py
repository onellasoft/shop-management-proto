"""Unit tests for AuthService.request_otp / verify_otp (Task 5.4).

Cover the mobile-number / OTP authentication behavior from Requirement 2:

* 2.1 — active + registered mobile → 6-digit OTP stored (10-min TTL) and sent.
* 2.2 — unknown mobile → silent (no error, no OTP generated/sent).
* 2.3 — non-active account → rejected without generating or sending an OTP.
* 2.4 — more than 3 requests / 10-min window → OTPRateLimitedError.
* 2.5 — matching, unexpired OTP → returns the authenticated user.
* 2.6 — mismatch → AuthenticationError + failure count incremented.
* 2.7 — 5 failures → stored OTP invalidated; further attempts rejected.
* 2.8 — verifying after expiry / never-requested → OTPExpiredError.
* 2.9 — successful verification invalidates the OTP so it cannot be reused.

These are pure-logic tests: the database boundary is replaced with a tiny fake
async session, and Redis is replaced with an in-memory ``OTPBackend`` fake.
The real ``OTPStore`` logic and a recording ``MockSmsSender`` are used
unchanged — nothing about the OTP rules is mocked.
"""

from __future__ import annotations

import pytest

from app.cache.otp_store import (
    MAX_FAILED_ATTEMPTS,
    OTP_DIGITS,
    RATE_LIMIT_MAX_REQUESTS,
    OTPStore,
)
from app.core.errors import (
    AuthenticationError,
    OTPExpiredError,
    OTPRateLimitedError,
)
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.sms_sender import MockSmsSender

MOBILE = "+15551234567"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value: User | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> User | None:
        return self._value


class _FakeSession:
    """Minimal AsyncSession stand-in returning a fixed user for any SELECT."""

    def __init__(self, user: User | None) -> None:
        self._user = user

    async def execute(self, _statement) -> _FakeResult:  # noqa: ANN001
        return _FakeResult(self._user)


class _InMemoryOTPBackend:
    """In-memory ``OTPBackend`` fake (no TTL expiry unless simulated).

    Implements the same async key/value protocol the ``OTPStore`` depends on.
    Expiry is not time-driven here; tests simulate expiry by clearing the store
    via :meth:`expire_all` to exercise the "OTP gone" path (Req 2.8).
    """

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        self.data[key] = value

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        value = int(self.data.get(key, "0")) + 1
        self.data[key] = str(value)
        return value

    def expire_all(self) -> None:
        """Simulate every stored key's TTL elapsing (Req 2.8)."""
        self.data.clear()


def _make_user(status: str = "active") -> User:
    return User(
        mobile=MOBILE,
        role_type="superadmin",
        status=status,
        failed_login_count=0,
        locked_until=None,
    )


def _build(
    user: User | None,
) -> tuple[AuthService, _InMemoryOTPBackend, MockSmsSender]:
    backend = _InMemoryOTPBackend()
    store = OTPStore(backend)
    sms = MockSmsSender()
    svc = AuthService(
        _FakeSession(user),  # type: ignore[arg-type]
        otp_store=store,
        sms_sender=sms,
    )
    return svc, backend, sms


# ---------------------------------------------------------------------------
# Req 2.1 — active + registered mobile → OTP stored and sent
# ---------------------------------------------------------------------------


async def test_request_otp_stores_six_digit_code_and_sends_sms() -> None:
    svc, _backend, sms = _build(_make_user())

    await svc.request_otp(MOBILE)

    assert len(sms.sent) == 1
    sent = sms.sent[0]
    assert sent.mobile == MOBILE
    # The dispatched message carries a zero-padded six-digit code.
    digits = [c for c in sent.message if c.isdigit()]
    assert len(digits) == OTP_DIGITS


async def test_request_otp_stored_code_matches_sent_code() -> None:
    svc, backend, sms = _build(_make_user())

    await svc.request_otp(MOBILE)

    stored = await svc._otp_store.get_otp(MOBILE)  # noqa: SLF001
    assert stored is not None
    assert stored in sms.sent[0].message


# ---------------------------------------------------------------------------
# Req 2.2 — unknown mobile → silent (no OTP, no error)
# ---------------------------------------------------------------------------


async def test_request_otp_unknown_mobile_is_silent_and_generates_no_otp() -> None:
    svc, _backend, sms = _build(None)

    # No exception is raised (non-enumerating) ...
    await svc.request_otp(MOBILE)

    # ... and nothing is stored or sent.
    assert sms.sent == []
    assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Req 2.3 — non-active account → rejected without generating/sending an OTP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["disabled", "inactive", "locked"])
async def test_request_otp_non_active_account_generates_no_otp(status: str) -> None:
    svc, _backend, sms = _build(_make_user(status=status))

    await svc.request_otp(MOBILE)

    assert sms.sent == []
    assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001


# ---------------------------------------------------------------------------
# Req 2.4 — more than 3 requests / 10-min window → rate limited
# ---------------------------------------------------------------------------


async def test_request_otp_rate_limited_after_three_requests() -> None:
    svc, _backend, sms = _build(_make_user())

    # First 3 requests succeed within the window.
    for _ in range(RATE_LIMIT_MAX_REQUESTS):
        await svc.request_otp(MOBILE)
    assert len(sms.sent) == RATE_LIMIT_MAX_REQUESTS

    # The 4th request exceeds the limit and is rejected.
    with pytest.raises(OTPRateLimitedError):
        await svc.request_otp(MOBILE)


# ---------------------------------------------------------------------------
# Req 2.5 / 2.9 — matching OTP authenticates and invalidates on success
# ---------------------------------------------------------------------------


async def test_verify_otp_matching_code_returns_user_and_invalidates() -> None:
    user = _make_user()
    svc, _backend, sms = _build(user)

    await svc.request_otp(MOBILE)
    code = [c for c in sms.sent[0].message if c.isdigit()]
    otp = "".join(code)

    result = await svc.verify_otp(MOBILE, otp)
    assert result is user

    # Req 2.9: the OTP is invalidated on success and cannot be reused.
    assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001
    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, otp)


# ---------------------------------------------------------------------------
# Req 2.6 — mismatch → auth error + failure count increment
# ---------------------------------------------------------------------------


async def test_verify_otp_mismatch_raises_and_counts_failure() -> None:
    svc, backend, sms = _build(_make_user())
    await svc.request_otp(MOBILE)

    with pytest.raises(AuthenticationError):
        await svc.verify_otp(MOBILE, "000000")  # wrong (store uses random code)

    # Failure counter recorded (shares the OTP key namespace under the hood).
    assert backend.data.get(f"otp:failures:{MOBILE}") == "1"


# ---------------------------------------------------------------------------
# Req 2.7 — 5 failures invalidate the OTP; further attempts rejected
# ---------------------------------------------------------------------------


async def test_verify_otp_invalidates_after_five_failures() -> None:
    svc, _backend, sms = _build(_make_user())
    await svc.request_otp(MOBILE)

    # Five mismatches trip invalidation (Req 2.7).
    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            await svc.verify_otp(MOBILE, "000000")

    # The stored OTP is now gone; further verification is rejected as expired.
    assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001
    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, "000000")


# ---------------------------------------------------------------------------
# Req 2.8 — verifying after expiry / never requested → expired error
# ---------------------------------------------------------------------------


async def test_verify_otp_never_requested_raises_expired() -> None:
    svc, _backend, _sms = _build(_make_user())

    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, "123456")


async def test_verify_otp_after_expiry_raises_expired() -> None:
    svc, backend, sms = _build(_make_user())
    await svc.request_otp(MOBILE)
    code = "".join(c for c in sms.sent[0].message if c.isdigit())

    # Simulate the 10-minute TTL elapsing.
    backend.expire_all()

    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, code)

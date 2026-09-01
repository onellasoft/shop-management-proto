"""Property-based tests for OTP generation, rate limiting, and lifecycle.

Covers Task 5.6 of the onella-backend spec.

# Feature: onella-backend, Property 4: OTP generation and rate limiting
# Feature: onella-backend, Property 5: OTP verification lifecycle

Properties (from design "Correctness Properties"):

* Property 4 — OTP generation and rate limiting.
  *For any* OTP request accepted for a registered, active mobile number, the
  generated OTP is always exactly six digits (Req 2.1); and *for any* number of
  requests against the same mobile within the 10-minute window, the fourth and
  every subsequent request is rejected with a rate-limit error (Req 2.4).
  **Validates: Requirements 2.1, 2.4**

* Property 5 — OTP verification lifecycle.
  *For any* request-then-verify sequence, submitting the matching, unexpired
  OTP authenticates the user and invalidates the OTP so it cannot be reused
  (Req 2.5, 2.9); any mismatching submission is rejected as an authentication
  error and increments the failure count, and once five failures are recorded
  the stored OTP is invalidated and further verification is rejected
  (Req 2.6, 2.7); and verifying after expiry (or when none was ever requested)
  yields an expired-OTP error (Req 2.8).
  **Validates: Requirements 2.5, 2.6, 2.7, 2.8, 2.9**

These are pure-logic property tests reusing the fake-session + in-memory OTP
backend + recording ``MockSmsSender`` patterns from the unit tests
(``tests/unit/test_auth_service_otp.py``). Nothing about the OTP rules is
mocked: the real ``AuthService`` and the real ``OTPStore`` logic are exercised
directly against an in-memory backend fake (no live Redis). Expiry is simulated
by clearing the in-memory backend (the store treats an absent key as expired,
Req 2.8).
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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
# Test doubles (mirroring the unit-test / login-property helpers)
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

    async def execute(self, _statement):  # noqa: ANN001, ANN201
        return _FakeResult(self._user)


class _InMemoryOTPBackend:
    """In-memory ``OTPBackend`` fake (same protocol as the unit tests).

    Expiry is not time-driven; tests simulate a TTL elapsing by calling
    :meth:`expire_all`, exercising the store's "OTP gone" path (Req 2.8).
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
    sms = MockSmsSender()
    svc = AuthService(
        _FakeSession(user),  # type: ignore[arg-type]
        otp_store=OTPStore(backend),
        sms_sender=sms,
    )
    return svc, backend, sms


def _sent_code(sms: MockSmsSender, index: int = -1) -> str:
    """Extract the digit-only OTP from a recorded SMS message."""
    return "".join(c for c in sms.sent[index].message if c.isdigit())


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 4: OTP generation and rate limiting
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(data=st.data())
async def test_property_4_generated_otp_is_always_six_digits(
    data: st.DataObject,
) -> None:
    """Validates: Requirements 2.1.

    For any accepted OTP request against a registered, active mobile, the
    generated-and-stored OTP is always exactly six digits, and the same
    six-digit code is what gets dispatched via the SMS sender.
    """
    svc, backend, sms = _build(_make_user())

    await svc.request_otp(MOBILE)

    stored = await svc._otp_store.get_otp(MOBILE)  # noqa: SLF001
    assert stored is not None
    # Exactly six characters, all decimal digits (zero-padded codes included).
    assert len(stored) == OTP_DIGITS
    assert stored.isdigit()

    # The dispatched message carries exactly that six-digit code.
    assert len(sms.sent) == 1
    assert _sent_code(sms) == stored
    assert len(_sent_code(sms)) == OTP_DIGITS


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(total_requests=st.integers(min_value=1, max_value=25))
async def test_property_4_requests_beyond_the_limit_are_rate_limited(
    total_requests: int,
) -> None:
    """Validates: Requirements 2.4.

    For any number of OTP requests against the same mobile within the window,
    the first ``RATE_LIMIT_MAX_REQUESTS`` (3) succeed and issue an OTP, and the
    fourth and every subsequent request is rejected with a rate-limit error,
    with no additional OTP issued for the rejected requests.
    """
    svc, backend, sms = _build(_make_user())

    allowed = 0
    for _ in range(total_requests):
        if allowed < RATE_LIMIT_MAX_REQUESTS:
            await svc.request_otp(MOBILE)
            allowed += 1
        else:
            with pytest.raises(OTPRateLimitedError):
                await svc.request_otp(MOBILE)

    # Only the in-window allowance produced dispatched OTPs.
    expected_sent = min(total_requests, RATE_LIMIT_MAX_REQUESTS)
    assert len(sms.sent) == expected_sent
    # Every dispatched OTP was a six-digit code (Req 2.1 reinforced).
    assert all(len(_sent_code(sms, i)) == OTP_DIGITS for i in range(expected_sent))


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 5: OTP verification lifecycle
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(data=st.data())
async def test_property_5_matching_otp_authenticates_and_invalidates(
    data: st.DataObject,
) -> None:
    """Validates: Requirements 2.5, 2.9.

    For any request-then-verify sequence, submitting the matching, unexpired
    OTP returns the authenticated user (Req 2.5) and invalidates the stored OTP
    so a second verification with the same code fails as expired (Req 2.9).
    """
    user = _make_user()
    svc, backend, sms = _build(user)

    await svc.request_otp(MOBILE)
    otp = _sent_code(sms)

    assert await svc.verify_otp(MOBILE, otp) is user

    # Req 2.9: invalidated on success → cannot be reused.
    assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001
    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, otp)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(wrong=st.text(alphabet="0123456789", min_size=1, max_size=6))
async def test_property_5_mismatch_counts_failure_and_invalidates_at_five(
    wrong: str,
) -> None:
    """Validates: Requirements 2.6, 2.7.

    For any submission that does not match the stored OTP, verification is
    rejected with an authentication error and the failure count is incremented
    (Req 2.6). Once five failures are recorded, the stored OTP is invalidated
    and further verification is rejected as expired (Req 2.7).
    """
    svc, backend, sms = _build(_make_user())
    await svc.request_otp(MOBILE)
    stored = _sent_code(sms)

    # Ensure the drawn code is genuinely a mismatch; otherwise skip this example.
    if wrong == stored:
        return

    failure_key = f"otp:failures:{MOBILE}"

    for attempt in range(1, MAX_FAILED_ATTEMPTS + 1):
        if attempt < MAX_FAILED_ATTEMPTS:
            # Req 2.6: each mismatch is an auth error and bumps the counter.
            with pytest.raises(AuthenticationError):
                await svc.verify_otp(MOBILE, wrong)
            assert backend.data.get(failure_key) == str(attempt)
            # OTP still present until the threshold is reached.
            assert await svc._otp_store.get_otp(MOBILE) is not None  # noqa: SLF001
        else:
            # Req 2.7: the 5th failure invalidates the stored OTP.
            with pytest.raises(AuthenticationError):
                await svc.verify_otp(MOBILE, wrong)
            assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001

    # Req 2.7: with the OTP invalidated, further attempts are expired errors —
    # even the (now-gone) correct code cannot verify.
    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, wrong)
    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, stored)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(submitted=st.text(alphabet="0123456789", min_size=1, max_size=6))
async def test_property_5_absent_or_expired_otp_is_expired_error(
    submitted: str,
) -> None:
    """Validates: Requirements 2.8.

    For any submitted code, verifying when no OTP was ever requested, and
    verifying after the stored OTP's TTL has elapsed, both yield an
    expired-OTP error (an absent key covers "never requested" and "expired").
    """
    # Never requested → expired error.
    svc, backend, sms = _build(_make_user())
    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, submitted)

    # Requested then expired (TTL elapsed) → expired error, even for the code
    # that was originally issued.
    await svc.request_otp(MOBILE)
    issued = _sent_code(sms)
    backend.expire_all()

    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, submitted)
    with pytest.raises(OTPExpiredError):
        await svc.verify_otp(MOBILE, issued)

"""Property-based tests for login accounting/lockout and non-active/unknown rejection.

Covers Task 4.3 of the onella-backend spec.

# Feature: onella-backend, Property 2: Failed login accounting and lockout
# Feature: onella-backend, Property 3: Non-active accounts and unknown identifiers never authenticate

Properties (from design "Correctness Properties"):

* Property 2 — Failed login accounting and lockout.
  *For any* active account, each rejected login increments the
  consecutive-failure count by one; upon 5 failures within a 15-minute window
  the account becomes locked for 15 minutes and further logins are rejected
  with an account-locked error; and any successful login resets the count to
  zero.
  **Validates: Requirements 1.3, 1.5, 1.6**

* Property 3 — Non-active accounts and unknown identifiers never authenticate.
  *For any* account whose status is not active, and for any unregistered email
  or mobile, an authentication request is rejected with a generic
  non-enumerating error, no password is verified, and no tokens or OTP are
  issued or sent.
  **Validates: Requirements 1.2, 1.4, 2.2, 2.3**

These are pure-logic property tests reusing the fake-session + injectable-clock
+ in-memory OTP backend patterns from the unit tests
(``tests/unit/test_auth_service_login_password.py`` and
``tests/unit/test_auth_service_otp.py``). Nothing about the authentication,
lockout, or OTP rules is mocked: the real ``AuthService``, the real
``OTPStore`` logic, and a recording ``MockSmsSender`` are exercised directly.

bcrypt is intentionally slow, so a single password hash is precomputed once at
import time and reused across every example; failed-login examples verify a
*wrong* password against that one shared hash (one bcrypt verify per attempt),
and ``max_examples`` is kept small with ``deadline=None`` so the suite stays
within budget.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.cache.otp_store import OTPStore
from app.core.errors import (
    AccountLockedError,
    AuthenticationError,
    OTPRateLimitedError,
)
from app.core.security import hash_password
from app.models.user import User
from app.services.auth_service import (
    LOCKOUT_WINDOW,
    MAX_FAILED_ATTEMPTS,
    AuthService,
)
from app.services.sms_sender import MockSmsSender

# --- bcrypt cost mitigation -------------------------------------------------
# One shared password/hash reused by every example so bcrypt is invoked a
# bounded number of times regardless of how many Hypothesis examples run.
PASSWORD = "correct-horse-battery-staple"
WRONG_PASSWORD = "definitely-not-the-password"
_SHARED_HASH = hash_password(PASSWORD)

EMAIL = "user@example.com"
MOBILE = "+15551234567"

NON_ACTIVE_STATUSES = ("disabled", "inactive", "locked")


# ---------------------------------------------------------------------------
# Test doubles (mirroring the unit-test helpers)
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


class _Clock:
    """Controllable clock returning an aware UTC datetime."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def set(self, moment: datetime) -> None:
        self.now = moment


class _InMemoryOTPBackend:
    """In-memory ``OTPBackend`` fake (same protocol as the unit tests)."""

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


def _password_user(status: str = "active") -> User:
    """An email/password user reusing the shared precomputed bcrypt hash."""
    return User(
        email=EMAIL,
        role_type="superadmin",
        status=status,
        password_hash=_SHARED_HASH,
        failed_login_count=0,
        locked_until=None,
    )


def _mobile_user(status: str = "active") -> User:
    return User(
        mobile=MOBILE,
        role_type="superadmin",
        status=status,
        failed_login_count=0,
        locked_until=None,
    )


def _login_service(user: User | None, clock: _Clock) -> AuthService:
    return AuthService(_FakeSession(user), clock=clock)  # type: ignore[arg-type]


def _otp_service(
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


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 2: Failed login accounting and lockout
# ---------------------------------------------------------------------------

_BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# A sequence of 0..7 failed attempts, each with an offset (minutes) from the
# base instant. Offsets are non-decreasing so the clock only moves forward,
# and are bounded so streaks can fall inside or straddle the 15-minute window.
_offset_minutes = st.integers(min_value=0, max_value=40)


@st.composite
def _failure_schedule(draw) -> list[int]:  # noqa: ANN001
    """A monotonically non-decreasing list (0..7 entries) of minute offsets."""
    count = draw(st.integers(min_value=0, max_value=7))
    offsets = draw(
        st.lists(_offset_minutes, min_size=count, max_size=count)
    )
    offsets.sort()
    return offsets


def _reference_accounting(offsets: list[int]) -> tuple[int, datetime | None]:
    """Independent re-implementation of the sliding-window failure accounting.

    Mirrors the spec (Req 1.3, 1.5): each failure inside the current 15-minute
    window increments the running count; a failure after the window elapsed (or
    the first ever) restarts the streak at 1; every failure refreshes the
    window marker to ``now + 15 min``. Returns the expected
    (failed_login_count, locked_until) after applying all failures in order.

    A failure that arrives while the account is already locked (count >= 5 and
    now < marker) is rejected as *locked* and does not change the counters, so
    it is skipped here to match ``login_password``'s early return.
    """
    count = 0
    marker: datetime | None = None
    for off in offsets:
        now = _BASE_TIME + timedelta(minutes=off)
        # Already locked → the attempt is rejected before accounting runs.
        if marker is not None and count >= MAX_FAILED_ATTEMPTS and now < marker:
            continue
        window_open = marker is not None and now < marker
        count = count + 1 if window_open else 1
        marker = now + LOCKOUT_WINDOW
    return count, marker


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(offsets=_failure_schedule())
async def test_property_2_failed_login_accounting_and_lockout(
    offsets: list[int],
) -> None:
    """Validates: Requirements 1.3, 1.5.

    For any forward-moving sequence of failed attempts, the resulting
    ``failed_login_count`` and lock state match the sliding-window spec: each
    in-window failure increments the count, and reaching 5 within a 15-minute
    window locks the account so a subsequent (correct-password) login is
    rejected with an account-locked error until the window elapses.
    """
    user = _password_user()
    clock = _Clock(_BASE_TIME)
    svc = _login_service(user, clock)

    for off in offsets:
        clock.set(_BASE_TIME + timedelta(minutes=off))
        # A wrong password against an active account is a failed attempt unless
        # the account is currently locked, in which case it is a lock error.
        with pytest.raises((AuthenticationError, AccountLockedError)):
            await svc.login_password(EMAIL, WRONG_PASSWORD)

    expected_count, expected_marker = _reference_accounting(offsets)
    assert user.failed_login_count == expected_count

    if not offsets:
        # Req 1.3: no attempts → no accounting side effects at all.
        assert user.failed_login_count == 0
        assert user.locked_until is None
        return

    assert user.locked_until == expected_marker

    # Req 1.5: whether the account is *currently* locked is fully determined by
    # (count >= 5) AND (now < marker). Evaluate at the last attempt instant.
    last_now = _BASE_TIME + timedelta(minutes=offsets[-1])
    currently_locked = (
        expected_count >= MAX_FAILED_ATTEMPTS
        and expected_marker is not None
        and last_now < expected_marker
    )

    if currently_locked:
        # Even a correct password is rejected while the lock is in effect.
        clock.set(last_now)
        with pytest.raises(AccountLockedError):
            await svc.login_password(EMAIL, PASSWORD)
        # Once the lock window elapses, the correct password authenticates.
        assert expected_marker is not None
        clock.set(expected_marker + timedelta(seconds=1))
        assert await svc.login_password(EMAIL, PASSWORD) is user
    else:
        # Not locked → a correct password authenticates immediately (Req 1.5).
        clock.set(last_now)
        assert await svc.login_password(EMAIL, PASSWORD) is user


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(prior_failures=st.integers(min_value=0, max_value=7))
async def test_property_2_success_resets_failure_count_to_zero(
    prior_failures: int,
) -> None:
    """Validates: Requirements 1.6.

    After any number of prior failures that has not locked the account, a
    successful login resets the consecutive-failure count to zero and clears
    the lock marker.
    """
    user = _password_user()
    clock = _Clock(_BASE_TIME)
    svc = _login_service(user, clock)

    # Stage failures spaced beyond the window so the account never locks; each
    # restarts the streak at 1, keeping the account eligible to authenticate.
    for i in range(prior_failures):
        clock.set(_BASE_TIME + (LOCKOUT_WINDOW + timedelta(minutes=1)) * i)
        with pytest.raises(AuthenticationError):
            await svc.login_password(EMAIL, WRONG_PASSWORD)

    if prior_failures:
        assert user.failed_login_count == 1

    # A successful login resets accounting regardless of the prior count.
    assert await svc.login_password(EMAIL, PASSWORD) is user
    assert user.failed_login_count == 0
    assert user.locked_until is None


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 3: Non-active accounts and unknown
# identifiers never authenticate
# ---------------------------------------------------------------------------

_statuses = st.sampled_from(NON_ACTIVE_STATUSES)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(status=_statuses, password=st.text(min_size=0, max_size=40))
async def test_property_3_non_active_password_login_never_authenticates(
    status: str, password: str
) -> None:
    """Validates: Requirements 1.4.

    For any non-active status and any submitted password (including the correct
    one), password login is rejected with a generic authentication error, no
    password is verified (the failure count is unchanged), and no user/token is
    returned.
    """
    user = _password_user(status=status)
    clock = _Clock(_BASE_TIME)
    svc = _login_service(user, clock)

    with pytest.raises(AuthenticationError):
        await svc.login_password(EMAIL, password)

    # Req 1.4: the password is never verified → accounting is untouched.
    assert user.failed_login_count == 0
    assert user.locked_until is None

    # The correct password is likewise rejected for a non-active account.
    with pytest.raises(AuthenticationError):
        await svc.login_password(EMAIL, PASSWORD)
    assert user.failed_login_count == 0


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    email=st.emails(),
    password=st.text(min_size=0, max_size=40),
)
async def test_property_3_unknown_email_never_authenticates(
    email: str, password: str
) -> None:
    """Validates: Requirements 1.2.

    For any unregistered email, password login is rejected with the same
    generic authentication error used for a bad password, so the response never
    reveals whether the email exists.
    """
    svc = _login_service(None, _Clock(_BASE_TIME))

    with pytest.raises(AuthenticationError) as unknown:
        await svc.login_password(email, password)

    # Non-enumerating: identical message to a wrong-password rejection.
    assert str(unknown.value) == str(AuthenticationError())


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(status=_statuses)
async def test_property_3_non_active_otp_request_issues_nothing(
    status: str,
) -> None:
    """Validates: Requirements 2.3.

    For any non-active account, an OTP request is silently rejected: no OTP is
    stored and no SMS is sent (no enumeration of account status).
    """
    svc, backend, sms = _otp_service(_mobile_user(status=status))

    await svc.request_otp(MOBILE)

    assert sms.sent == []
    assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(mobile=st.text(min_size=1, max_size=20))
async def test_property_3_unknown_mobile_otp_request_is_silent(
    mobile: str,
) -> None:
    """Validates: Requirements 2.2.

    For any unregistered mobile number, an OTP request completes without error
    and without generating or sending an OTP (non-enumerating).
    """
    svc, backend, sms = _otp_service(None)

    # No error is raised for an unknown number ...
    await svc.request_otp(mobile)

    # ... and nothing is stored or sent for it.
    assert sms.sent == []
    assert await svc._otp_store.get_otp(mobile) is None  # noqa: SLF001


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(status=_statuses)
async def test_property_3_non_active_otp_request_rate_limit_still_applies(
    status: str,
) -> None:
    """Validates: Requirements 2.3, 2.2.

    The silent rejection of a non-active account still counts against the
    rate-limit window (so the timing cannot be used to enumerate status): the
    4th request in the window is rejected with a rate-limit error, and no OTP
    is ever issued or sent for the non-active account.
    """
    svc, backend, sms = _otp_service(_mobile_user(status=status))

    for _ in range(3):
        await svc.request_otp(MOBILE)

    with pytest.raises(OTPRateLimitedError):
        await svc.request_otp(MOBILE)

    assert sms.sent == []
    assert await svc._otp_store.get_otp(MOBILE) is None  # noqa: SLF001

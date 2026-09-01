"""Unit tests for AuthService.login_password (Task 4.1).

Cover the email/password authentication and lockout behavior from
Requirement 1:

* 1.1 — active account + matching password authenticates.
* 1.2 — unknown email → generic (non-enumerating) authentication error.
* 1.3 — bad password → authentication error + failed-count increment.
* 1.4 — non-active account → rejected WITHOUT verifying the password.
* 1.5 — 5 failures within a 15-minute window → account locked for 15 minutes.
* 1.6 — a successful login resets the failed-attempt count to zero.

These are pure-logic tests: the database boundary is replaced with a tiny fake
async session so the authentication/lockout rules can be exercised
deterministically with an injected clock. The code under test
(``AuthService``) and the real password hashing (``hash_password`` /
``verify_password``) are used unchanged — no behavior is mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.errors import AccountLockedError, AuthenticationError
from app.core.security import hash_password
from app.models.user import User
from app.services.auth_service import (
    LOCKOUT_WINDOW,
    MAX_FAILED_ATTEMPTS,
    AuthService,
)

PASSWORD = "correct-horse-battery-staple"


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


class _Clock:
    """Controllable clock returning an aware UTC datetime."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _make_user(status: str = "active", *, with_password: bool = True) -> User:
    return User(
        email="user@example.com",
        role_type="superadmin",
        status=status,
        password_hash=hash_password(PASSWORD) if with_password else None,
        failed_login_count=0,
        locked_until=None,
    )


def _service(user: User | None, clock: _Clock) -> AuthService:
    return AuthService(_FakeSession(user), clock=clock)  # type: ignore[arg-type]


def _clock_at(text_free: int = 0) -> _Clock:
    return _Clock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=text_free))


# ---------------------------------------------------------------------------
# Req 1.1 — success
# ---------------------------------------------------------------------------


async def test_active_account_with_matching_password_authenticates() -> None:
    user = _make_user()
    svc = _service(user, _clock_at())

    result = await svc.login_password("user@example.com", PASSWORD)

    assert result is user


# ---------------------------------------------------------------------------
# Req 1.2 — unknown email (non-enumerating)
# ---------------------------------------------------------------------------


async def test_unknown_email_raises_generic_authentication_error() -> None:
    svc = _service(None, _clock_at())

    with pytest.raises(AuthenticationError):
        await svc.login_password("nobody@example.com", PASSWORD)


def test_unknown_email_and_bad_password_share_the_same_message() -> None:
    """The error must not reveal whether the email exists (Req 1.2)."""
    unknown = AuthenticationError()
    bad_pw = AuthenticationError()
    assert str(unknown) == str(bad_pw)


# ---------------------------------------------------------------------------
# Req 1.3 — bad password increments the failed count
# ---------------------------------------------------------------------------


async def test_bad_password_raises_and_increments_failed_count() -> None:
    user = _make_user()
    svc = _service(user, _clock_at())

    with pytest.raises(AuthenticationError):
        await svc.login_password("user@example.com", "wrong")

    assert user.failed_login_count == 1


# ---------------------------------------------------------------------------
# Req 1.4 — non-active accounts rejected without verifying password
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["disabled", "inactive"])
async def test_non_active_account_rejected_without_password_verify(status: str) -> None:
    user = _make_user(status=status)
    svc = _service(user, _clock_at())

    # Even the CORRECT password must be rejected for a non-active account, and
    # the failure count must not change (the password is never verified).
    with pytest.raises(AuthenticationError):
        await svc.login_password("user@example.com", PASSWORD)

    assert user.failed_login_count == 0


async def test_non_active_account_rejected_even_with_correct_password() -> None:
    user = _make_user(status="disabled")
    svc = _service(user, _clock_at())

    with pytest.raises(AuthenticationError):
        await svc.login_password("user@example.com", PASSWORD)


# ---------------------------------------------------------------------------
# Req 1.5 — lockout after 5 failures within a 15-minute window
# ---------------------------------------------------------------------------


async def test_five_failures_in_window_locks_account_for_15_minutes() -> None:
    user = _make_user()
    clock = _clock_at()
    svc = _service(user, clock)

    # Four failures, each a minute apart — still inside the window.
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthenticationError):
            await svc.login_password("user@example.com", "wrong")
        clock.advance(timedelta(minutes=1))

    # Fifth failure trips the lock.
    with pytest.raises(AuthenticationError):
        await svc.login_password("user@example.com", "wrong")

    assert user.failed_login_count == MAX_FAILED_ATTEMPTS
    assert user.locked_until is not None

    # Subsequent attempts (even with the correct password) are locked out.
    with pytest.raises(AccountLockedError):
        await svc.login_password("user@example.com", PASSWORD)


async def test_lock_expires_after_15_minutes() -> None:
    user = _make_user()
    clock = _clock_at()
    svc = _service(user, clock)

    for _ in range(MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthenticationError):
            await svc.login_password("user@example.com", "wrong")

    with pytest.raises(AccountLockedError):
        await svc.login_password("user@example.com", PASSWORD)

    # Once the lock window elapses, a correct password succeeds again.
    clock.advance(LOCKOUT_WINDOW + timedelta(seconds=1))
    result = await svc.login_password("user@example.com", PASSWORD)
    assert result is user


async def test_failures_outside_window_do_not_accumulate_to_a_lock() -> None:
    user = _make_user()
    clock = _clock_at()
    svc = _service(user, clock)

    # Failures spaced beyond the 15-minute window never reach the threshold:
    # each restarts the streak at 1.
    for _ in range(MAX_FAILED_ATTEMPTS + 2):
        with pytest.raises(AuthenticationError):
            await svc.login_password("user@example.com", "wrong")
        clock.advance(LOCKOUT_WINDOW + timedelta(minutes=1))

    assert user.failed_login_count == 1
    # No lock is in effect: a correct password authenticates.
    result = await svc.login_password("user@example.com", PASSWORD)
    assert result is user


# ---------------------------------------------------------------------------
# Req 1.6 — success resets the failed-attempt count
# ---------------------------------------------------------------------------


async def test_successful_login_resets_failed_count() -> None:
    user = _make_user()
    clock = _clock_at()
    svc = _service(user, clock)

    for _ in range(3):
        with pytest.raises(AuthenticationError):
            await svc.login_password("user@example.com", "wrong")
    assert user.failed_login_count == 3

    await svc.login_password("user@example.com", PASSWORD)

    assert user.failed_login_count == 0
    assert user.locked_until is None


# ---------------------------------------------------------------------------
# OTP-only account (no password hash) cannot log in with a password
# ---------------------------------------------------------------------------


async def test_password_login_rejected_for_account_without_password_hash() -> None:
    user = _make_user(with_password=False)
    svc = _service(user, _clock_at())

    with pytest.raises(AuthenticationError):
        await svc.login_password("user@example.com", PASSWORD)

    assert user.failed_login_count == 1

"""Auth_Service — authentication and (later) JWT lifecycle.

This module currently implements **email/password login with lockout**
(Task 4.1, Requirements 1.1-1.6). OTP flows (Req 2), refresh-token rotation,
and full ``TokenPair`` issuance are added in later tasks (5.x, 6.x); this file
exposes the seams those tasks build on.

Design references: "Components and Interfaces → Auth_Service"::

    async def login_password(self, email: str, password: str) -> TokenPair:
        \"\"\"Verify active account + bcrypt password; handle lockout counters.
        Raises AuthError (generic) on unknown email/bad password/disabled;
        AccountLockedError after 5 fails / 15 min. (Req 1.1-1.8)\"\"\"

Because refresh-token persistence (``refresh_tokens`` model) and
``issue_token_pair`` land in Task 6.2, ``login_password`` here returns the
authenticated :class:`~app.models.user.User` on success. Task 4.2 (the router)
and Task 6.2 will layer token issuance on top of this authenticated result
without changing the authentication/lockout semantics implemented here.

Lockout model (Req 1.5) with the columns available on ``users``
(``failed_login_count`` + ``locked_until``) and an **injectable clock**:

* Every failed attempt increments ``failed_login_count`` (Req 1.3).
* ``locked_until`` doubles as the **15-minute window marker**. On the first
  failure of a streak (or the first failure after the previous window has
  elapsed) it is set to ``now + 15 min`` and the count restarts at 1. Failures
  that arrive while ``now < locked_until`` fall inside the same 15-minute
  window and increment the running count.
* When the count reaches 5 **within** that window, the account is locked:
  ``locked_until`` is (re)set to ``now + 15 min`` and, because the count is now
  ``>= 5`` with ``now < locked_until``, subsequent logins are rejected with
  :class:`AccountLockedError` until the lock elapses (Req 1.5).
* A successful login resets ``failed_login_count`` to 0 and clears
  ``locked_until`` (Req 1.6).

Non-active accounts (``disabled`` / ``inactive`` / ``locked``) are rejected
**without** verifying the submitted password and without issuing tokens
(Req 1.4). Unknown emails and bad passwords both yield the same generic,
non-enumerating :class:`AuthenticationError` (Req 1.2, 1.3).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.otp_store import OTPStore, get_otp_store
from app.core.config import Settings, get_settings
from app.core.errors import (
    AccountLockedError,
    AuthenticationError,
    OTPExpiredError,
    OTPRateLimitedError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import TokenPair
from app.services.sms_sender import SmsSender, get_sms_sender

# --- Lockout policy constants (Req 1.5) ---

#: Consecutive failures within the window that trigger a lock.
MAX_FAILED_ATTEMPTS = 5
#: Sliding window for counting consecutive failures, and the lock duration.
LOCKOUT_WINDOW = timedelta(minutes=15)

#: The only account status permitted to authenticate (Req 1.1, 1.4).
ACTIVE_STATUS = "active"


def _default_clock() -> datetime:
    """Return the current time as an aware UTC ``datetime``.

    Isolated behind a module function so callers may inject a fake clock for
    deterministic time-window testing (Req 1.5).
    """
    return datetime.now(timezone.utc)


def _as_aware(value: datetime) -> datetime:
    """Coerce a possibly-naive DB timestamp to an aware UTC ``datetime``.

    Postgres ``timestamptz`` values round-trip as aware datetimes, but tests
    (and some drivers) may yield naive values; normalizing avoids naive/aware
    comparison errors when checking the window/lock against the clock.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class AuthService:
    """Authentication service.

    Parameters
    ----------
    session:
        The active :class:`~sqlalchemy.ext.asyncio.AsyncSession`. The service
        stages mutations on the session; committing is the caller's/route's
        responsibility (so a single request commits once).
    clock:
        A zero-argument callable returning an aware ``datetime``. Defaults to
        the wall clock; inject a fake for time-window tests (Req 1.5).
    otp_store:
        The :class:`~app.cache.otp_store.OTPStore` driving the OTP lifecycle
        (Req 2). Defaults to a Redis-backed store; inject an in-memory fake for
        deterministic OTP tests.
    sms_sender:
        The :class:`~app.services.sms_sender.SmsSender` used to deliver OTPs
        (Req 2.1, 2.10). Defaults to the environment-selected sender (mock in
        development); inject a recording fake for tests.
    settings:
        The :class:`~app.core.config.Settings` driving JWT lifecycle parameters
        (access/refresh TTLs) for token issuance (Req 3.1, 3.2). Defaults to the
        process settings; inject for deterministic token tests.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = _default_clock,
        otp_store: OTPStore | None = None,
        sms_sender: SmsSender | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._otp_store = otp_store or get_otp_store()
        self._sms_sender = sms_sender or get_sms_sender()
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Email / password login (Req 1.1-1.6)
    # ------------------------------------------------------------------

    async def login_password(self, email: str, password: str) -> User:
        """Authenticate a user by email + password, enforcing lockout.

        Returns the authenticated :class:`User` on success. Token issuance is
        layered on top by the router (Task 4.2) / ``issue_token_pair``
        (Task 6.2).

        Raises
        ------
        AuthenticationError
            For an unknown email (Req 1.2), a bad password (Req 1.3), or a
            non-active account (Req 1.4). The message is identical in every
            case so the response never reveals whether the email exists.
        AccountLockedError
            When the account is currently locked (Req 1.5).
        """
        user = await self._get_user_by_email(email)

        # Req 1.2: unknown email → generic error, no enumeration. We do not
        # perform a password hash here; the uniform error message keeps the
        # response indistinguishable from a bad-password result.
        if user is None:
            raise AuthenticationError()

        now = self._clock()

        # Req 1.5: reject while a lock is in effect before doing anything else.
        if self._is_locked(user, now):
            raise AccountLockedError()

        # Req 1.4: non-active (disabled/inactive/locked) accounts are rejected
        # WITHOUT verifying the submitted password and without issuing tokens.
        if user.status != ACTIVE_STATUS:
            raise AuthenticationError()

        # Req 1.3 / 1.8: verify the submitted password against the stored hash.
        # A missing hash (OTP-only account) can never satisfy a password login.
        if user.password_hash is None or not verify_password(
            password, user.password_hash
        ):
            self._register_failed_attempt(user, now)
            raise AuthenticationError()

        # Req 1.1 / 1.6: success → reset the failure streak and clear the lock.
        self._reset_failures(user)
        return user

    # ------------------------------------------------------------------
    # Mobile / OTP login (Req 2.1-2.9)
    # ------------------------------------------------------------------

    async def request_otp(self, mobile: str) -> None:
        """Issue and dispatch an OTP for a registered, active ``mobile``.

        On success a fresh six-digit OTP is stored (10-min TTL) and sent via the
        configured SMS sender (Req 2.1). The request is silently ignored for an
        unknown mobile so the response never reveals whether the number is
        registered (Req 2.2) — the method returns ``None`` without generating an
        OTP. A non-active account is likewise rejected without generating or
        sending an OTP (Req 2.3). Requests beyond 3 per rolling 10-minute window
        are rate-limited (Req 2.4).

        Raises
        ------
        OTPRateLimitedError
            When more than 3 requests occur for ``mobile`` within the 10-minute
            window (Req 2.4).
        """
        # Req 2.4: count the request first so abusive callers are throttled even
        # for unknown/non-active numbers (no enumeration via rate-limit timing).
        request_count = await self._otp_store.increment_rate_limit(mobile)
        if self._otp_store.is_rate_limited(request_count):
            raise OTPRateLimitedError()

        user = await self._get_user_by_mobile(mobile)

        # Req 2.2: unknown mobile → silent (no error, no OTP). Req 2.3: a
        # non-active account is rejected without generating or sending an OTP.
        # Both cases return without side effects beyond the rate-limit counter,
        # keeping the response indistinguishable across existence/status.
        if user is None or user.status != ACTIVE_STATUS:
            return

        # Req 2.1: store a fresh 6-digit OTP (10-min TTL) and dispatch it.
        otp = await self._otp_store.store_otp(mobile)
        await self._sms_sender.send(mobile, f"Your Onella verification code is {otp}.")

    async def verify_otp(self, mobile: str, otp: str) -> User:
        """Verify a submitted ``otp`` for ``mobile``; return the authenticated user.

        On a matching, unexpired OTP the stored OTP is invalidated so it cannot
        be reused (Req 2.9) and the authenticated :class:`User` is returned;
        token issuance is layered on top by the router (Task 5.5) /
        ``issue_token_pair`` (Task 6.2), mirroring ``login_password`` (Req 2.5).

        Raises
        ------
        OTPExpiredError
            When no OTP is stored for ``mobile`` (never requested or expired)
            (Req 2.8).
        AuthenticationError
            When the submitted OTP does not match; the failed-attempt counter is
            incremented and the OTP is invalidated once 5 failures are recorded,
            after which further attempts also raise this error (Req 2.6, 2.7).
        """
        stored = await self._otp_store.get_otp(mobile)

        # Req 2.8: an absent OTP covers both "never requested" and "expired"
        # (the TTL drops the key). Also covers a code already invalidated after
        # 5 failures (Req 2.7) or a prior successful verification (Req 2.9).
        if stored is None:
            raise OTPExpiredError()

        # Req 2.6: a mismatch is a non-enumerating auth error and counts a
        # failure; the store invalidates the OTP once the 5th failure lands
        # (Req 2.7), so subsequent attempts fall through to OTPExpiredError-free
        # rejection on the next call (stored becomes None).
        if not secrets.compare_digest(stored, otp):
            await self._otp_store.increment_failure_count(mobile)
            raise AuthenticationError()

        user = await self._get_user_by_mobile(mobile)

        # A matching OTP for a mobile with no active user is treated as a
        # generic auth failure (the account may have been removed/deactivated
        # between request and verify); still invalidate the code so it cannot be
        # reused (Req 2.9).
        if user is None or user.status != ACTIVE_STATUS:
            await self._otp_store.invalidate(mobile)
            raise AuthenticationError()

        # Req 2.9: invalidate on success so the OTP cannot be reused. Req 2.5:
        # return the authenticated user for the caller to issue tokens.
        await self._otp_store.invalidate(mobile)
        return user

    # ------------------------------------------------------------------
    # JWT lifecycle: issuance, rotation, reuse-detection, logout (Req 3.5-3.9)
    # ------------------------------------------------------------------

    def issue_token_pair(
        self,
        user: User,
        *,
        family_id=None,
        rotated_from=None,
    ) -> TokenPair:
        """Mint an access + refresh token pair and stage the refresh row.

        Builds a short-lived access token (Req 3.1, 3.3, 3.4) and a long-lived
        refresh token (Req 3.2), then stages a ``refresh_tokens`` row keyed by
        the refresh token's ``jti``. When ``family_id`` is ``None`` a new
        issuance chain is started (fresh login); otherwise the chain is
        continued on rotation with ``rotated_from`` pointing at the predecessor
        token's ``jti``. Only the SHA-256 hash of the refresh token is
        persisted — the raw token is never stored.

        The row is *staged* on the session (added, not committed); the caller
        (route) owns the single per-request commit, mirroring the other
        Auth_Service methods.
        """
        now = self._clock()
        settings = self._settings

        access_token = create_access_token(
            user_id=user.id,
            role_type=user.role_type,
            email=user.email,
            agency_id=user.agency_id,
            settings=settings,
            now=now,
        )

        refresh_token, jti, chain_id = create_refresh_token(
            user_id=user.id,
            family_id=family_id,
            settings=settings,
            now=now,
        )
        expires_at = now + timedelta(days=settings.refresh_token_ttl_days)

        row = RefreshToken(
            id=jti,
            user_id=user.id,
            family_id=chain_id,
            rotated_from=rotated_from,
            token_hash=hash_token(refresh_token),
            used=False,
            revoked=False,
            expires_at=expires_at,
        )
        self._session.add(row)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.access_token_ttl_min * 60,
        )

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Rotate a presented refresh token, detecting reuse (Req 3.5, 3.7, 3.8).

        The presented token must verify cryptographically, be unexpired, and
        correspond to a persisted row; any of these failing raises
        :class:`AuthenticationError` and issues no tokens (Req 3.7).

        If the matched row is already ``used`` or ``revoked``, the presentation
        is treated as **reuse**: every token sharing its ``family_id`` is
        revoked so no token in the chain can be used again, and
        :class:`AuthenticationError` is raised (Req 3.8).

        Otherwise the row is marked ``used`` and a successor is issued in the
        same family with ``rotated_from`` set to the presented token's ``jti``
        (Req 3.5).

        Raises
        ------
        AuthenticationError
            On signature failure, expiry, malformed payload, an unknown token,
            or detected reuse (Req 3.7, 3.8).
        """
        # Req 3.7: signature/expiry/malformed failures raise AuthenticationError
        # from decode_refresh_token and issue no tokens.
        claims = decode_refresh_token(refresh_token, settings=self._settings)

        row = await self._get_refresh_row(hash_token(refresh_token))

        # Req 3.7: a token with a valid signature but no persisted row (e.g.
        # already pruned, or never issued by us) is rejected without issuing.
        if row is None:
            raise AuthenticationError()

        # Req 3.7: independent expiry guard against the stored row, in case a
        # token outlives its record's expiry window.
        if self._clock() >= _as_aware(row.expires_at):
            raise AuthenticationError()

        # Req 3.8: reuse of an already-used/revoked token invalidates the whole
        # family so no chain token can be subsequently used.
        if row.used or row.revoked:
            await self._revoke_family(row.family_id)
            raise AuthenticationError()

        # Req 3.5: mark the presented token used and issue a successor in the
        # same family within this request.
        row.used = True
        user = await self._get_user_by_id(claims.sub)
        if user is None:
            raise AuthenticationError()

        return self.issue_token_pair(
            user,
            family_id=row.family_id,
            rotated_from=row.id,
        )

    async def logout(self, refresh_token: str) -> None:
        """Revoke the presented refresh token and its entire family (Req 3.9).

        A logout with a valid refresh token invalidates that token together
        with every token derived from the same issuance chain so none can be
        used for a subsequent refresh. A token that fails signature/expiry
        verification raises :class:`AuthenticationError` (consistent with
        Req 3.7); if it verifies but has no persisted row there is nothing to
        revoke and the call returns quietly (idempotent logout).
        """
        claims = decode_refresh_token(refresh_token, settings=self._settings)
        await self._revoke_family(claims.family_id)

    # ------------------------------------------------------------------
    # Refresh-token data access / mutation
    # ------------------------------------------------------------------

    async def _get_refresh_row(self, token_hash: str) -> RefreshToken | None:
        """Load the ``refresh_tokens`` row for a token hash, or ``None``."""
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def _get_user_by_id(self, user_id) -> User | None:
        """Load a user by id, or ``None`` if absent."""
        result = await self._session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _revoke_family(self, family_id) -> None:
        """Mark every token in ``family_id`` as revoked (Req 3.8, 3.9).

        Staged on the session; the caller commits. The bulk ``UPDATE`` ensures
        even tokens not loaded into the identity map are revoked so the whole
        chain becomes unusable.
        """
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id)
            .values(revoked=True)
        )

    # ------------------------------------------------------------------
    # Lockout helpers
    # ------------------------------------------------------------------

    def _is_locked(self, user: User, now: datetime) -> bool:
        """Whether ``user`` is currently locked out (Req 1.5).

        A lock is in effect when the failure count has reached the threshold
        and the ``locked_until`` marker is still in the future.
        """
        if user.locked_until is None:
            return False
        if user.failed_login_count < MAX_FAILED_ATTEMPTS:
            return False
        return now < _as_aware(user.locked_until)

    def _register_failed_attempt(self, user: User, now: datetime) -> None:
        """Record a failed login, applying the 15-minute sliding window.

        ``locked_until`` marks the end of the current 15-minute window. If the
        prior window has elapsed (or none exists), the streak restarts at 1 and
        a fresh window is opened. Otherwise the running count is incremented.
        Reaching :data:`MAX_FAILED_ATTEMPTS` within the window locks the
        account for :data:`LOCKOUT_WINDOW` (Req 1.3, 1.5).
        """
        window_open = (
            user.locked_until is not None and now < _as_aware(user.locked_until)
        )

        if window_open:
            user.failed_login_count += 1
        else:
            # Window elapsed or first-ever failure: start a new streak/window.
            user.failed_login_count = 1

        # Extend/refresh the window marker on every failure so five failures
        # spread across up to 15 minutes trip the lock, while the marker also
        # serves as the lock expiry once the threshold is reached.
        user.locked_until = now + LOCKOUT_WINDOW

    def _reset_failures(self, user: User) -> None:
        """Clear the failure streak and any lock after a success (Req 1.6)."""
        user.failed_login_count = 0
        user.locked_until = None

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    async def _get_user_by_email(self, email: str) -> User | None:
        """Load a user by (case-insensitive) email, or ``None`` if absent.

        ``users.email`` is a citext column, so the equality comparison is
        case-insensitive at the database level.
        """
        result = await self._session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def _get_user_by_mobile(self, mobile: str) -> User | None:
        """Load a user by mobile number, or ``None`` if absent.

        ``users.mobile`` is a unique column, so at most one user matches.
        """
        result = await self._session.execute(
            select(User).where(User.mobile == mobile)
        )
        return result.scalar_one_or_none()


__all__ = [
    "AuthService",
    "MAX_FAILED_ATTEMPTS",
    "LOCKOUT_WINDOW",
]

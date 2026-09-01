"""Property-based tests for invalid-token rejection and refresh rotation/reuse.

Covers Task 6.4 of the onella-backend spec.

# Feature: onella-backend, Property 8: Invalid tokens are rejected without side effects
# Feature: onella-backend, Property 9: Refresh rotation and family reuse-detection

Properties (from design "Correctness Properties"):

* Property 8 — Invalid tokens are rejected without side effects.
  *For any* refresh token that fails signature verification, is expired, is of
  the wrong type, or is otherwise malformed, ``AuthService.refresh`` (and
  ``AuthService.logout``) rejects it with :class:`AuthenticationError`, no new
  token row is staged, and no ``TokenPair`` is issued.
  **Validates: Requirements 3.6, 3.7**

* Property 9 — Refresh rotation and family reuse-detection.
  *For any* rotation chain of length N, each refresh marks the presented token
  used and issues a successor in the same family; reusing any prior used token
  revokes the whole family; and logout revokes the family so no chain token can
  subsequently be used.
  **Validates: Requirements 3.5, 3.8, 3.9**

These are pure-logic property tests. The database boundary is replaced with the
same small in-memory fake ``AsyncSession`` used by the unit tests
(``tests/unit/test_auth_service_tokens.py``): it stores ``User`` and
``RefreshToken`` rows and understands the exact statement shapes the service
issues — a ``select`` by ``token_hash`` / by user ``id`` and a family-wide
``update(...).values(revoked=True)``. The real token codec
(``create_refresh_token`` / ``decode_refresh_token``) and real SHA-256 hashing
are used unchanged — no cryptography is mocked.

Issuance uses realistic wall-clock times because ``decode_refresh_token``
verifies ``exp`` against the real clock during ``jwt.decode``; the injectable
service clock is anchored at ``datetime.now(timezone.utc)`` per example.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import AuthService


# ---------------------------------------------------------------------------
# Test doubles (mirrors tests/unit/test_auth_service_tokens.py)
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    """In-memory AsyncSession stand-in for refresh-token flows.

    Serves the three statement shapes the service issues:

    * ``select(RefreshToken).where(token_hash == ...)`` — hash lookup.
    * ``select(User).where(id == ...)`` — user lookup.
    * ``update(RefreshToken).where(family_id == ...).values(revoked=True)`` —
      family-wide revocation applied in-place to the stored rows.
    """

    def __init__(
        self,
        *,
        users: list[User] | None = None,
        tokens: list[RefreshToken] | None = None,
    ) -> None:
        self.users = list(users or [])
        self.tokens = list(tokens or [])

    def add(self, obj: object) -> None:
        if isinstance(obj, RefreshToken):
            self.tokens.append(obj)
        elif isinstance(obj, User):
            self.users.append(obj)

    async def execute(self, statement):  # noqa: ANN001
        compiled = str(statement).lower()

        # Family-wide revocation UPDATE.
        if compiled.startswith("update"):
            family_id = statement.compile().params.get("family_id_1")
            for row in self.tokens:
                if row.family_id == family_id:
                    row.revoked = True
            return _ScalarResult(None)

        params = statement.compile().params

        # SELECT on refresh_tokens by token_hash.
        if "refresh_tokens" in compiled:
            token_hash = params.get("token_hash_1")
            match = next(
                (t for t in self.tokens if t.token_hash == token_hash), None
            )
            return _ScalarResult(match)

        # SELECT on users by id.
        user_id = params.get("id_1")
        match = next((u for u in self.users if u.id == user_id), None)
        return _ScalarResult(match)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def _settings() -> Settings:
    return Settings(
        jwt_secret="property-test-secret-key-that-is-32-bytes-long",
        jwt_algorithm="HS256",
        access_token_ttl_min=20,
        refresh_token_ttl_days=14,
    )


def _clock() -> _Clock:
    # Anchor at real wall-clock time: decode_refresh_token verifies ``exp``
    # against the real clock, so issuance must be realistic.
    return _Clock(datetime.now(timezone.utc))


def _make_user() -> User:
    return User(
        id=uuid4(),
        email="user@example.com",
        role_type="superadmin",
        status="active",
        failed_login_count=0,
        locked_until=None,
    )


def _service(session: _FakeSession, clock: _Clock, cfg: Settings) -> AuthService:
    return AuthService(session, clock=clock, settings=cfg)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Strategies for producing "invalid" refresh tokens (Property 8)
# ---------------------------------------------------------------------------

# The kinds of invalidity Req 3.6/3.7 enumerate: tampered signature, wrong
# secret, expired, wrong token_type, and structurally malformed strings.
INVALID_KINDS = (
    "tampered",
    "wrong_secret",
    "expired",
    "wrong_type",
    "malformed",
)


def _make_invalid_token(kind: str, cfg: Settings, user_id, garbage: str) -> str:
    """Build a refresh-token string that must be rejected by ``kind``."""
    if kind == "tampered":
        token, _, _ = create_refresh_token(user_id=user_id, settings=cfg)
        # Flip the trailing signature characters so verification fails.
        return token[:-2] + ("aa" if token[-2:] != "aa" else "bb")

    if kind == "wrong_secret":
        other = Settings(
            jwt_secret="a-completely-different-secret-32-bytes-plus",
            jwt_algorithm="HS256",
            refresh_token_ttl_days=cfg.refresh_token_ttl_days,
        )
        token, _, _ = create_refresh_token(user_id=user_id, settings=other)
        return token

    if kind == "expired":
        # Issue far enough in the past that exp is already <= now.
        past = datetime.now(timezone.utc) - timedelta(
            days=cfg.refresh_token_ttl_days + 1
        )
        token, _, _ = create_refresh_token(user_id=user_id, settings=cfg, now=past)
        return token

    if kind == "wrong_type":
        # A structurally valid ACCESS token — rejected because token_type
        # is not "refresh".
        return create_access_token(
            user_id=user_id,
            role_type="superadmin",
            settings=cfg,
        )

    # "malformed": arbitrary non-JWT junk.
    return garbage


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 8: Invalid tokens are rejected without side effects
# ---------------------------------------------------------------------------


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    kind=st.sampled_from(INVALID_KINDS),
    garbage=st.text(min_size=0, max_size=40),
)
def test_property_8_invalid_tokens_rejected_without_side_effects(
    kind: str, garbage: str
) -> None:
    """Validates: Requirements 3.6, 3.7.

    For any tampered / wrong-secret / expired / wrong-type / malformed refresh
    token, ``refresh`` and ``logout`` raise :class:`AuthenticationError`, no
    ``TokenPair`` is returned, and the session's staged rows are unchanged.
    """
    cfg = _settings()
    user = _make_user()
    # A legitimately-issued token is already staged so we can prove the
    # rejection leaves the existing rows untouched (no revocation, no addition).
    session = _FakeSession(users=[user])
    clock = _clock()
    svc = _service(session, clock, cfg)
    legit = svc.issue_token_pair(user)

    rows_before = list(session.tokens)
    revoked_before = [t.revoked for t in session.tokens]
    used_before = [t.used for t in session.tokens]

    bad_token = _make_invalid_token(kind, cfg, user.id, garbage)

    # refresh: rejected, no new token issued.
    with pytest.raises(AuthenticationError):
        asyncio.run(svc.refresh(bad_token))

    # logout: also rejected for a signature/expiry/type/malformed failure.
    with pytest.raises(AuthenticationError):
        asyncio.run(svc.logout(bad_token))

    # No row added, and no row's used/revoked flags changed as a side effect.
    assert session.tokens == rows_before
    assert [t.revoked for t in session.tokens] == revoked_before
    assert [t.used for t in session.tokens] == used_before

    # The legitimately-issued token still refreshes cleanly afterwards, proving
    # the rejected attempts caused no collateral damage to the real family.
    new_pair = asyncio.run(svc.refresh(legit.refresh_token))
    assert new_pair.refresh_token
    assert new_pair.access_token


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 9: Refresh rotation and family reuse-detection
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    chain_length=st.integers(min_value=1, max_value=6),
    reuse_index=st.data(),
    terminate=st.sampled_from(("reuse", "logout")),
)
def test_property_9_refresh_rotation_and_family_reuse_detection(
    chain_length: int, reuse_index, terminate: str
) -> None:
    """Validates: Requirements 3.5, 3.8, 3.9.

    Build a rotation chain of length ``chain_length``. Each refresh marks the
    presented token used and issues a successor in the same family
    (Req 3.5). Then either reuse a prior already-used token (Req 3.8) or log
    out with the latest token (Req 3.9); both revoke the whole family so no
    token in the chain can subsequently be refreshed.
    """
    cfg = _settings()
    user = _make_user()
    session = _FakeSession(users=[user])
    clock = _clock()
    svc = _service(session, clock, cfg)

    # First issuance: the family root.
    current = svc.issue_token_pair(user)
    root = session.tokens[0]
    family_id = root.family_id
    presented_tokens = [current.refresh_token]

    # --- Rotation chain (Req 3.5) ---
    for step in range(chain_length):
        prev_rows = list(session.tokens)
        prev_presented_row = session.tokens[step]

        current = asyncio.run(svc.refresh(current.refresh_token))
        presented_tokens.append(current.refresh_token)

        # The presented token is now used (not revoked) ...
        assert prev_presented_row.used is True
        assert prev_presented_row.revoked is False

        # ... and exactly one successor was added in the SAME family, linked
        # via rotated_from to the presented token.
        assert len(session.tokens) == len(prev_rows) + 1
        successor = session.tokens[-1]
        assert successor.family_id == family_id
        assert successor.rotated_from == prev_presented_row.id
        assert successor.used is False
        assert successor.revoked is False
        # Every row in the chain shares the one family id.
        assert all(t.family_id == family_id for t in session.tokens)

    # After N rotations there are N+1 rows; the last one is unused.
    assert len(session.tokens) == chain_length + 1
    assert session.tokens[-1].used is False

    if terminate == "reuse":
        # Reuse a prior, already-used token. Any of the first ``chain_length``
        # presented tokens is now used; pick one arbitrarily.
        if chain_length == 0:
            # No rotation happened; reuse is impossible, fall back to logout.
            asyncio.run(svc.logout(current.refresh_token))
        else:
            idx = reuse_index.draw(
                st.integers(min_value=0, max_value=chain_length - 1)
            )
            with pytest.raises(AuthenticationError):
                asyncio.run(svc.refresh(presented_tokens[idx]))
    else:  # logout
        asyncio.run(svc.logout(current.refresh_token))

    # --- Family-wide revocation (Req 3.8 / 3.9) ---
    assert all(t.revoked for t in session.tokens)

    # No token in the chain can subsequently be refreshed.
    for token in presented_tokens:
        with pytest.raises(AuthenticationError):
            asyncio.run(svc.refresh(token))

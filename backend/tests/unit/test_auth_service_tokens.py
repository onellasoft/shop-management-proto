"""Unit tests for AuthService token lifecycle (Task 6.2).

Cover refresh-token issuance, rotation, reuse-detection, and logout from
Requirement 3:

* 3.5 — a valid, unexpired, unused refresh token rotates: the presented token
  is marked used and a successor is issued in the same family.
* 3.7 — a refresh token that fails signature/expiry verification, or has no
  persisted row, is rejected and issues no tokens.
* 3.8 — presenting an already-used/revoked token (reuse) revokes the entire
  family so no chain token can be used again.
* 3.9 — logout revokes the presented token and its whole family.

These are pure-logic tests: the database boundary is replaced with a small
in-memory fake ``AsyncSession`` that stores ``RefreshToken`` and ``User`` rows
and understands the two statement shapes the service issues — a ``select`` (by
token_hash / by user id) and a family-wide ``update(...).values(revoked=True)``.
The real token codec (``create_refresh_token`` / ``decode_refresh_token``) and
the real SHA-256 hashing are used unchanged — no cryptography is mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError
from app.core.security import create_refresh_token, hash_token
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import AuthService


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _FakeSession:
    """In-memory AsyncSession stand-in for refresh-token flows.

    Stores users and refresh-token rows in plain lists. ``add`` appends a newly
    minted row; ``execute`` inspects the SQLAlchemy statement to serve the two
    query/mutation shapes the service uses:

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
    # Explicit, in-bounds TTLs so token expiry math is deterministic.
    return Settings(
        jwt_secret="unit-test-secret",
        jwt_algorithm="HS256",
        access_token_ttl_min=20,
        refresh_token_ttl_days=14,
    )


def _clock() -> _Clock:
    # Anchor near real wall-clock time: the token codec verifies ``exp`` against
    # the real clock during ``jwt.decode``, so issuance time must be realistic.
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


def _service(session: _FakeSession, clock: _Clock, settings: Settings) -> AuthService:
    return AuthService(session, clock=clock, settings=settings)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# issue_token_pair — first issuance stages a family-root row
# ---------------------------------------------------------------------------


def test_issue_token_pair_stages_new_family_row() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    clock = _clock()
    settings = _settings()
    svc = _service(session, clock, settings)

    pair = svc.issue_token_pair(user)

    assert pair.access_token
    assert pair.refresh_token
    assert pair.token_type == "bearer"
    assert pair.expires_in == settings.access_token_ttl_min * 60

    # Exactly one row staged; it is the family root (no rotated_from).
    assert len(session.tokens) == 1
    row = session.tokens[0]
    assert row.user_id == user.id
    assert row.rotated_from is None
    assert row.used is False
    assert row.revoked is False
    # Only the hash is stored, never the raw token.
    assert row.token_hash == hash_token(pair.refresh_token)
    assert row.token_hash != pair.refresh_token


# ---------------------------------------------------------------------------
# Req 3.5 — rotation: presented token marked used, successor issued in family
# ---------------------------------------------------------------------------


async def test_refresh_rotates_and_marks_presented_token_used() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    clock = _clock()
    settings = _settings()
    svc = _service(session, clock, settings)

    first = svc.issue_token_pair(user)
    root = session.tokens[0]

    new_pair = await svc.refresh(first.refresh_token)

    # The presented (root) token is now used, not revoked.
    assert root.used is True
    assert root.revoked is False

    # A successor row exists in the SAME family, rotated_from the root.
    assert len(session.tokens) == 2
    successor = session.tokens[1]
    assert successor.family_id == root.family_id
    assert successor.rotated_from == root.id
    assert successor.used is False
    assert successor.revoked is False
    assert successor.token_hash == hash_token(new_pair.refresh_token)
    # The successor is a distinct token.
    assert new_pair.refresh_token != first.refresh_token


# ---------------------------------------------------------------------------
# Req 3.8 — reuse of a used token revokes the entire family
# ---------------------------------------------------------------------------


async def test_reusing_used_token_revokes_whole_family() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    clock = _clock()
    settings = _settings()
    svc = _service(session, clock, settings)

    first = svc.issue_token_pair(user)
    # Legitimate rotation: first -> second.
    await svc.refresh(first.refresh_token)

    # Now REUSE the already-used first token.
    with pytest.raises(AuthenticationError):
        await svc.refresh(first.refresh_token)

    # Every token in the family is revoked (both root and successor).
    assert all(t.revoked for t in session.tokens)


async def test_reusing_revoked_token_revokes_whole_family() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    clock = _clock()
    settings = _settings()
    svc = _service(session, clock, settings)

    pair = svc.issue_token_pair(user)
    # Directly mark the row revoked (e.g. by a prior logout).
    session.tokens[0].revoked = True

    with pytest.raises(AuthenticationError):
        await svc.refresh(pair.refresh_token)

    assert all(t.revoked for t in session.tokens)


# ---------------------------------------------------------------------------
# Req 3.7 — invalid / expired / unknown tokens are rejected without issuing
# ---------------------------------------------------------------------------


async def test_refresh_rejects_tampered_signature() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    svc = _service(session, _clock(), _settings())

    pair = svc.issue_token_pair(user)
    tampered = pair.refresh_token[:-2] + ("aa" if pair.refresh_token[-2:] != "aa" else "bb")

    before = len(session.tokens)
    with pytest.raises(AuthenticationError):
        await svc.refresh(tampered)
    # No new token was staged.
    assert len(session.tokens) == before


async def test_refresh_rejects_token_signed_with_other_secret() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    svc = _service(session, _clock(), _settings())

    # A refresh token signed with a DIFFERENT secret must fail verification.
    other = Settings(jwt_secret="a-different-secret", jwt_algorithm="HS256")
    foreign_token, _, _ = create_refresh_token(user_id=user.id, settings=other)

    with pytest.raises(AuthenticationError):
        await svc.refresh(foreign_token)


async def test_refresh_rejects_unknown_token_with_no_row() -> None:
    user = _make_user()
    # Session has the user but NO refresh rows staged.
    session = _FakeSession(users=[user])
    settings = _settings()
    svc = _service(session, _clock(), settings)

    # A validly-signed token that was never persisted has no row.
    token, _, _ = create_refresh_token(user_id=user.id, settings=settings)

    with pytest.raises(AuthenticationError):
        await svc.refresh(token)


async def test_refresh_rejects_expired_token() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    clock = _clock()
    settings = _settings()
    svc = _service(session, clock, settings)

    pair = svc.issue_token_pair(user)

    # Advance past the refresh TTL: both the JWT exp and the row expiry lapse.
    clock.advance(timedelta(days=settings.refresh_token_ttl_days) + timedelta(seconds=1))

    with pytest.raises(AuthenticationError):
        await svc.refresh(pair.refresh_token)


# ---------------------------------------------------------------------------
# Req 3.9 — logout revokes the presented token and the whole family
# ---------------------------------------------------------------------------


async def test_logout_revokes_whole_family() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    clock = _clock()
    settings = _settings()
    svc = _service(session, clock, settings)

    first = svc.issue_token_pair(user)
    # Rotate once so the family has two rows.
    second = await svc.refresh(first.refresh_token)

    await svc.logout(second.refresh_token)

    # Both the presented token and its entire chain are revoked.
    assert all(t.revoked for t in session.tokens)

    # A subsequent refresh of any family token is now rejected.
    with pytest.raises(AuthenticationError):
        await svc.refresh(second.refresh_token)


async def test_logout_rejects_invalid_token() -> None:
    user = _make_user()
    session = _FakeSession(users=[user])
    svc = _service(session, _clock(), _settings())

    with pytest.raises(AuthenticationError):
        await svc.logout("not-a-real-jwt")

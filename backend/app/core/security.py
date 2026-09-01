"""Security primitives: password hashing and JWT encode/decode.

This module centralizes the cryptographic building blocks used across the
authentication and authorization flows:

* **Password hashing** — bcrypt via passlib (Req 1.7, 1.8). Passwords are
  stored only as bcrypt hashes and verified against the stored hash.
* **JWT lifecycle** — PyJWT encode/decode for the short-lived *access* token
  and the long-lived *refresh* token (Req 3.1-3.4).

References (design "JWT Token Structure & Lifecycle"):

Access token payload (Req 3.3, 3.4)::

    {
        "sub": "<user_id>",
        "email": "user@example.com",
        "role_type": "customeradmin",
        "agency_id": null,
        "customer_id": null,
        "token_type": "access",
        "iat": 1730000000,
        "exp": 1730001800
    }

* Access token expiry: configurable 15-30 min (``ACCESS_TOKEN_TTL_MIN``,
  default 20). (Req 3.1)
* Refresh token expiry: configurable 7-30 days (``REFRESH_TOKEN_TTL_DAYS``,
  default 14). (Req 3.2)
* For a customeradmin assigned to multiple customers, the accessible
  customer-id list is **not** embedded; it is resolved per request from
  ``customer_users``. (Req 3.4)
* ``agency_id`` / ``customer_id`` may be null. (Req 3.3)

Decoding rejects a token whose signature fails, whose ``exp`` is at or before
now, whose ``token_type`` does not match what the caller expects, or whose
payload is malformed — raising :class:`~app.core.errors.AuthenticationError`
so the caller can leave the requested operation unperformed (Req 3.6).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import bcrypt
import jwt

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError

# ---------------------------------------------------------------------------
# Token type constants
# ---------------------------------------------------------------------------

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


# ---------------------------------------------------------------------------
# Password hashing (Req 1.7, 1.8)
# ---------------------------------------------------------------------------

# bcrypt truncates inputs at 72 bytes. To support passwords of any length
# without silent truncation, we pre-hash the UTF-8 password with SHA-256 and
# base64-encode the digest (44 bytes, well under the limit) before bcrypt.
# This is the standard bcrypt "long password" mitigation and keeps a fresh
# random salt and configurable work factor per hash.
_BCRYPT_ROUNDS = 12


def _prehash(password: str) -> bytes:
    """SHA-256 pre-hash a password to a fixed 44-byte, bcrypt-safe input."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` (Req 1.7).

    A fresh random salt is generated per call, so hashing the same password
    twice yields different strings that both verify. Inputs longer than
    bcrypt's 72-byte limit are supported via a SHA-256 pre-hash.
    """
    hashed = bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify ``password`` against a stored bcrypt ``password_hash`` (Req 1.8).

    Returns ``False`` (rather than raising) for a mismatch or for a malformed
    stored hash, so callers can treat all verification failures uniformly with
    a generic, non-enumerating authentication error.
    """
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Refresh-token hashing (Req 3.5, 3.8, 3.9)
# ---------------------------------------------------------------------------


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a refresh ``token``.

    The raw refresh token is never persisted; only this deterministic digest is
    stored in ``refresh_tokens.token_hash`` so a presented token can be looked
    up by re-hashing it. SHA-256 (rather than bcrypt) is deliberate here: the
    lookup must be by exact value, and the token itself is already a
    high-entropy signed JWT, so a fast keyed-by-hash lookup is appropriate.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# JWT payloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessTokenClaims:
    """Decoded, validated claims from an access token (Req 3.3, 3.4).

    ``agency_id`` and ``customer_id`` may be ``None``. The accessible
    customer-id list for a multi-customer customeradmin is deliberately NOT
    part of the token; it is resolved per request from ``customer_users``.
    """

    sub: UUID
    email: str | None
    role_type: str
    agency_id: UUID | None
    customer_id: UUID | None
    iat: int
    exp: int
    token_type: str = ACCESS_TOKEN_TYPE


@dataclass(frozen=True)
class RefreshTokenClaims:
    """Decoded, validated claims from a refresh token (Req 3.2, 3.5).

    ``jti`` is the token's unique id (matches the ``refresh_tokens.id`` row).
    ``family_id`` identifies the issuance chain so reuse-detection can revoke
    an entire family.
    """

    sub: UUID
    jti: UUID
    family_id: UUID
    iat: int
    exp: int
    token_type: str = REFRESH_TOKEN_TYPE


def _now() -> datetime:
    """Current UTC time (isolated for testability)."""
    return datetime.now(timezone.utc)


def _uuid_or_none(value: Any) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))


# ---------------------------------------------------------------------------
# Access token (Req 3.1, 3.3, 3.4)
# ---------------------------------------------------------------------------


def create_access_token(
    *,
    user_id: UUID | str,
    role_type: str,
    email: str | None = None,
    agency_id: UUID | str | None = None,
    customer_id: UUID | str | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> str:
    """Encode a signed access token for the given user claims.

    The payload matches the design's access-token structure exactly. Expiry is
    ``ACCESS_TOKEN_TTL_MIN`` minutes from issuance (configurable 15-30, default
    20 — Req 3.1). The multi-customer accessible list is intentionally excluded
    (Req 3.4).
    """
    settings = settings or get_settings()
    issued_at = now or _now()
    expires_at = issued_at + timedelta(minutes=settings.access_token_ttl_min)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role_type": role_type,
        "agency_id": str(agency_id) if agency_id is not None else None,
        "customer_id": str(customer_id) if customer_id is not None else None,
        "token_type": ACCESS_TOKEN_TYPE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ---------------------------------------------------------------------------
# Refresh token (Req 3.2, 3.5)
# ---------------------------------------------------------------------------


def create_refresh_token(
    *,
    user_id: UUID | str,
    family_id: UUID | str | None = None,
    jti: UUID | str | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> tuple[str, UUID, UUID]:
    """Encode a signed refresh token.

    Returns a tuple of ``(token, jti, family_id)`` so the caller can persist a
    ``refresh_tokens`` row keyed by ``jti`` within the given ``family_id``. A
    new ``family_id`` is minted when none is supplied (first token in a chain);
    an existing one is continued on rotation.

    Expiry is ``REFRESH_TOKEN_TTL_DAYS`` days from issuance (configurable 7-30,
    default 14 — Req 3.2).
    """
    settings = settings or get_settings()
    issued_at = now or _now()
    expires_at = issued_at + timedelta(days=settings.refresh_token_ttl_days)

    token_id = UUID(str(jti)) if jti is not None else uuid4()
    chain_id = UUID(str(family_id)) if family_id is not None else uuid4()

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "jti": str(token_id),
        "family_id": str(chain_id),
        "token_type": REFRESH_TOKEN_TYPE,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, token_id, chain_id


# ---------------------------------------------------------------------------
# Decode / verify (Req 3.6)
# ---------------------------------------------------------------------------


def decode_token(
    token: str,
    *,
    expected_type: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decode and verify a JWT, returning its raw claims dict.

    Verifies the signature and expiry (``exp``). When ``expected_type`` is
    provided, the token's ``token_type`` must match. Any failure — invalid
    signature, expired token, wrong/missing type, or otherwise malformed
    payload — raises :class:`AuthenticationError` (Req 3.6), leaving the
    caller's operation unperformed.
    """
    settings = settings or get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("The token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("The token is invalid.") from exc

    if expected_type is not None and claims.get("token_type") != expected_type:
        raise AuthenticationError("The token type is not valid for this operation.")

    return claims


def decode_access_token(
    token: str, *, settings: Settings | None = None
) -> AccessTokenClaims:
    """Decode an access token into validated :class:`AccessTokenClaims`.

    Enforces ``token_type == "access"`` and coerces identifier fields. Raises
    :class:`AuthenticationError` on any malformed field (Req 3.6).
    """
    claims = decode_token(token, expected_type=ACCESS_TOKEN_TYPE, settings=settings)
    try:
        return AccessTokenClaims(
            sub=UUID(str(claims["sub"])),
            email=claims.get("email"),
            role_type=claims["role_type"],
            agency_id=_uuid_or_none(claims.get("agency_id")),
            customer_id=_uuid_or_none(claims.get("customer_id")),
            iat=int(claims["iat"]),
            exp=int(claims["exp"]),
            token_type=ACCESS_TOKEN_TYPE,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError("The token payload is malformed.") from exc


def decode_refresh_token(
    token: str, *, settings: Settings | None = None
) -> RefreshTokenClaims:
    """Decode a refresh token into validated :class:`RefreshTokenClaims`.

    Enforces ``token_type == "refresh"`` and coerces identifier fields. Raises
    :class:`AuthenticationError` on any malformed field (Req 3.6, 3.7).
    """
    claims = decode_token(token, expected_type=REFRESH_TOKEN_TYPE, settings=settings)
    try:
        return RefreshTokenClaims(
            sub=UUID(str(claims["sub"])),
            jti=UUID(str(claims["jti"])),
            family_id=UUID(str(claims["family_id"])),
            iat=int(claims["iat"]),
            exp=int(claims["exp"]),
            token_type=REFRESH_TOKEN_TYPE,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError("The token payload is malformed.") from exc

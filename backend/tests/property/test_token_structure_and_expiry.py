"""Property tests for JWT token structure and expiry bounds.

Covers Task 3.3 of the onella-backend spec. These tests exercise the token
helpers in ``app.core.security`` with generated user claims and settings,
using injectable ``now`` and ``settings`` so the assertions are deterministic
and independent of wall-clock time or the process-wide configuration.

Properties (from design "Correctness Properties"):

* Property 6 — Access token structure and expiry bounds (Req 3.1, 3.3, 3.4)
* Property 7 — Refresh token expiry bound (Req 3.2)
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import jwt
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.core.config import Settings
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

MIN_ACCESS_TTL_MIN = 15
MAX_ACCESS_TTL_MIN = 30
MIN_REFRESH_TTL_DAYS = 7
MAX_REFRESH_TTL_DAYS = 30

ROLE_TYPES = ("superadmin", "agencyadmin", "customeradmin")

# The customer-id list that must NEVER be embedded in an access token (Req 3.4).
# Property 6 asserts none of these generated ids leak into the encoded payload.
_FORBIDDEN_LIST_KEYS = (
    "customer_ids",
    "customers",
    "accessible_customers",
    "accessible_customer_ids",
    "customer_list",
)


def _decode_payload(token: str, cfg: Settings) -> dict:
    """Decode and verify signature, but not runtime expiry.

    These properties concern token *structure* and the *issuance bound*
    (exp - iat) for a deterministically injected issuance instant that may lie
    anywhere in a wide generated range. Verifying against the real wall clock
    would conflate the issuance bound with runtime-expiry rejection (which is a
    separate property). We therefore verify the signature but disable ``exp``
    enforcement here.
    """
    return jwt.decode(
        token,
        cfg.jwt_secret,
        algorithms=[cfg.jwt_algorithm],
        options={"verify_exp": False, "verify_iat": False},
    )


def _settings_with(access_ttl_min: int, refresh_ttl_days: int) -> Settings:
    """Build an isolated Settings instance with explicit TTLs.

    Using a fresh Settings (rather than the process singleton) keeps the test
    independent of environment configuration and lets Hypothesis sweep the
    full valid TTL range.
    """
    return Settings(
        jwt_secret="test-secret-key",
        jwt_algorithm="HS256",
        access_token_ttl_min=access_ttl_min,
        refresh_token_ttl_days=refresh_ttl_days,
    )


uuids = st.builds(uuid4)
emails = st.emails()
role_types = st.sampled_from(ROLE_TYPES)
# agency_id / customer_id are permitted to be null (Req 3.3).
optional_uuids = st.one_of(st.none(), uuids)
# A fixed, timezone-aware issuance instant per example for determinism.
issue_times = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2035, 1, 1),
).map(lambda dt: dt.replace(tzinfo=timezone.utc))

access_ttls = st.integers(min_value=MIN_ACCESS_TTL_MIN, max_value=MAX_ACCESS_TTL_MIN)
refresh_ttls = st.integers(
    min_value=MIN_REFRESH_TTL_DAYS, max_value=MAX_REFRESH_TTL_DAYS
)


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 6: Access token structure and expiry bounds
# ---------------------------------------------------------------------------


@hyp_settings(max_examples=200)
@given(
    user_id=uuids,
    email=st.one_of(st.none(), emails),
    role_type=role_types,
    agency_id=optional_uuids,
    customer_id=optional_uuids,
    now=issue_times,
    access_ttl_min=access_ttls,
    # Generate a list of accessible customer ids that must NOT leak into the token.
    accessible_customer_ids=st.lists(uuids, min_size=0, max_size=5),
)
def test_property_6_access_token_structure_and_expiry_bounds(
    user_id: UUID,
    email: str | None,
    role_type: str,
    agency_id: UUID | None,
    customer_id: UUID | None,
    now: datetime,
    access_ttl_min: int,
    accessible_customer_ids: list[UUID],
) -> None:
    """Validates: Requirements 3.1, 3.3, 3.4.

    For generated user claims, a decoded access token:
    * contains sub, email, role_type, agency_id, customer_id, iat, exp,
      token_type (agency_id/customer_id permitted to be null) — Req 3.3;
    * has a lifetime (exp - iat) within the 15-30 minute bound per settings — Req 3.1;
    * never embeds a customeradmin's accessible-customer-id list — Req 3.4.
    """
    cfg = _settings_with(access_ttl_min, MIN_REFRESH_TTL_DAYS)

    token = create_access_token(
        user_id=user_id,
        role_type=role_type,
        email=email,
        agency_id=agency_id,
        customer_id=customer_id,
        settings=cfg,
        now=now,
    )

    # --- Raw payload: exact key set, values, and type marker (Req 3.3) ---
    raw = _decode_payload(token, cfg)
    assert raw["sub"] == str(user_id)
    assert raw["email"] == email
    assert raw["role_type"] == role_type
    assert raw["agency_id"] == (str(agency_id) if agency_id is not None else None)
    assert raw["customer_id"] == (
        str(customer_id) if customer_id is not None else None
    )
    assert raw["token_type"] == ACCESS_TOKEN_TYPE
    assert isinstance(raw["iat"], int)
    assert isinstance(raw["exp"], int)

    expected_keys = {
        "sub",
        "email",
        "role_type",
        "agency_id",
        "customer_id",
        "iat",
        "exp",
        "token_type",
    }
    assert set(raw.keys()) == expected_keys

    # --- Accessible-customer list is never embedded (Req 3.4) ---
    for forbidden in _FORBIDDEN_LIST_KEYS:
        assert forbidden not in raw
    # No claim value carries the accessible-customer list either.
    forbidden_str = {str(cid) for cid in accessible_customer_ids}
    for value in raw.values():
        assert not isinstance(value, list)
        if isinstance(value, str):
            assert value not in forbidden_str or value in {
                str(user_id),
                str(agency_id),
                str(customer_id),
            }

    # --- Expiry bound: 15-30 minutes (Req 3.1) ---
    lifetime_seconds = raw["exp"] - raw["iat"]
    assert MIN_ACCESS_TTL_MIN * 60 <= lifetime_seconds <= MAX_ACCESS_TTL_MIN * 60
    # Exactly the configured TTL relative to the injected issuance instant.
    assert lifetime_seconds == access_ttl_min * 60
    assert raw["iat"] == int(now.timestamp())


# ---------------------------------------------------------------------------
# Feature: onella-backend, Property 7: Refresh token expiry bound
# ---------------------------------------------------------------------------


@hyp_settings(max_examples=200)
@given(
    user_id=uuids,
    family_id=optional_uuids,
    jti=optional_uuids,
    now=issue_times,
    refresh_ttl_days=refresh_ttls,
)
def test_property_7_refresh_token_expiry_bound(
    user_id: UUID,
    family_id: UUID | None,
    jti: UUID | None,
    now: datetime,
    refresh_ttl_days: int,
) -> None:
    """Validates: Requirements 3.2.

    For any issued refresh token, its lifetime (exp - iat) is within the
    7-30 day bound per settings.
    """
    cfg = _settings_with(MIN_ACCESS_TTL_MIN, refresh_ttl_days)

    token, token_id, chain_id = create_refresh_token(
        user_id=user_id,
        family_id=family_id,
        jti=jti,
        settings=cfg,
        now=now,
    )

    raw = _decode_payload(token, cfg)
    assert raw["sub"] == str(user_id)
    assert raw["jti"] == str(token_id)
    assert raw["family_id"] == str(chain_id)
    assert raw["token_type"] == REFRESH_TOKEN_TYPE
    if family_id is not None:
        assert raw["family_id"] == str(family_id)
    if jti is not None:
        assert raw["jti"] == str(jti)

    # --- Expiry bound: 7-30 days (Req 3.2) ---
    lifetime_seconds = raw["exp"] - raw["iat"]
    seconds_per_day = 24 * 60 * 60
    assert (
        MIN_REFRESH_TTL_DAYS * seconds_per_day
        <= lifetime_seconds
        <= MAX_REFRESH_TTL_DAYS * seconds_per_day
    )
    assert lifetime_seconds == refresh_ttl_days * seconds_per_day
    assert raw["iat"] == int(now.timestamp())

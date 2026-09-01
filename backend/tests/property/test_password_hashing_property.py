"""Property-based tests for password hashing round-trip.

# Feature: onella-backend, Property 1: Password hashing round-trip

**Validates: Requirements 1.7, 1.8**

Property 1 states that bcrypt hashing and verification form a correct
round-trip: for any password string, ``verify_password`` accepts the exact
password against its own hash, and rejects any *different* password against
that hash.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.security import hash_password, verify_password


# Any text password is valid input. The security module pre-hashes with
# SHA-256 before bcrypt, so passwords beyond bcrypt's 72-byte limit (including
# long unicode strings) must still round-trip correctly.
_passwords = st.text(min_size=0, max_size=200)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(password=_passwords)
def test_hash_verify_round_trip_accepts_matching_password(password: str) -> None:
    """verify_password(pw, hash_password(pw)) is always True (Req 1.7, 1.8)."""
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(password=_passwords, other=_passwords)
def test_hash_verify_rejects_different_password(password: str, other: str) -> None:
    """A different password never verifies against another's hash (Req 1.8).

    When ``other != password``, verifying ``other`` against ``password``'s hash
    must return False. (Equal inputs are excluded so this asserts only the
    mismatch case; the matching case is covered above.)
    """
    hashed = hash_password(password)
    if other != password:
        assert verify_password(other, hashed) is False
    else:
        assert verify_password(other, hashed) is True

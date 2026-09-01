"""Pydantic v2 request/response schemas for authentication endpoints.

Backs the ``/auth/*`` router (Task 4.2 and the later OTP/refresh/logout tasks).
This module currently defines the email/password login request and the shared
:class:`TokenPair` response used across every auth flow.

Design reference ("Components and Interfaces → Auth_Service")::

    TokenPair = {access_token, refresh_token, token_type="bearer", expires_in}

``expires_in`` is the access token's lifetime in **seconds** (derived from
``ACCESS_TOKEN_TTL_MIN``), letting the client schedule a refresh before expiry.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Email/password login payload (Req 1.1).

    Both fields are required. Validation failures surface through the central
    ``validation_error`` envelope; authentication failures are reported by the
    service with the generic, non-enumerating ``authentication_error`` so the
    response never reveals whether the email exists (Req 1.2).
    """

    email: str = Field(..., description="The account email address.")
    password: str = Field(..., description="The account password.")


class TokenPair(BaseModel):
    """Access + refresh token pair returned by every auth flow.

    Mirrors the design's ``TokenPair`` shape exactly:
    ``{access_token, refresh_token, token_type="bearer", expires_in}``.
    ``token_type`` is the OAuth-style bearer scheme label and defaults to
    ``"bearer"``. ``expires_in`` is the access token TTL in seconds.
    """

    access_token: str = Field(..., description="Short-lived signed access token.")
    refresh_token: str = Field(..., description="Long-lived signed refresh token.")
    token_type: str = Field(
        default="bearer",
        description="Bearer authentication scheme label.",
    )
    expires_in: int = Field(
        ...,
        description="Access token lifetime in seconds.",
    )


class OtpRequest(BaseModel):
    """OTP request payload for ``POST /auth/otp/request`` (Req 2.1).

    Carries only the mobile number to send a one-time password to. The endpoint
    always returns the same generic acknowledgement regardless of whether the
    mobile is registered, so this schema never leaks account existence (Req 2.2).
    """

    mobile: str = Field(..., description="The mobile number to send an OTP to.")


class OtpVerifyRequest(BaseModel):
    """OTP verification payload for ``POST /auth/otp/verify`` (Req 2.5).

    Both fields are required. On a matching, unexpired OTP the endpoint issues a
    :class:`TokenPair`; mismatches and expired/consumed codes surface through the
    service's generic authentication / expired-OTP errors.
    """

    mobile: str = Field(..., description="The mobile number the OTP was sent to.")
    otp: str = Field(..., description="The one-time password to verify.")


class RefreshRequest(BaseModel):
    """Refresh-token rotation payload for ``POST /auth/refresh`` (Req 3.5).

    Carries the presented refresh token to rotate. On a valid, unexpired,
    un-reused token the endpoint issues a fresh :class:`TokenPair` and marks the
    presented token used; a reused/invalid/expired token surfaces through the
    service's generic authentication error (Req 3.7, 3.8).
    """

    refresh_token: str = Field(..., description="The refresh token to rotate.")


class LogoutRequest(BaseModel):
    """Logout payload for ``POST /auth/logout`` (Req 3.9).

    Carries the refresh token to revoke. Logging out invalidates the presented
    token and its entire issuance family so none can be used for a subsequent
    refresh. A token that fails signature/expiry verification surfaces the
    generic authentication error (Req 3.7).
    """

    refresh_token: str = Field(..., description="The refresh token to revoke.")


__all__ = [
    "LoginRequest",
    "TokenPair",
    "OtpRequest",
    "OtpVerifyRequest",
    "RefreshRequest",
    "LogoutRequest",
]

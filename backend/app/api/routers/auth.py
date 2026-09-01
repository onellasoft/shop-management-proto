"""Authentication router (``/auth``).

Exposes the authentication endpoints for the Onella backend. This module owns
the single ``auth`` :class:`~fastapi.APIRouter` that every auth flow hangs off,
so later tasks can append their endpoints here without touching ``main.py``:

* Task 4.2: ``POST /auth/login`` — email/password → :class:`TokenPair`.
* Task 5.4/5.5: ``POST /auth/otp/request`` and ``POST /auth/otp/verify``.
* Task 6.3 (this task): ``POST /auth/refresh`` and ``POST /auth/logout``.

Token issuance
--------------
Refresh-token persistence and family rotation live in
:meth:`AuthService.issue_token_pair` (Task 6.2). Every endpoint here that mints
a token pair routes through that service method so a ``refresh_tokens`` row is
persisted (family/rotation bookkeeping) and end-to-end refresh rotation and
reuse-detection work. Because :func:`~app.db.session.get_db` commits the
session on successful request completion, endpoints stage their mutations and
rely on that single per-request commit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    OtpRequest,
    OtpVerifyRequest,
    RefreshRequest,
    TokenPair,
)
from app.services.auth_service import AuthService

# Single shared router for all /auth endpoints. Every auth flow (login, OTP,
# refresh, logout) registers its routes on this same instance so the app
# factory wires authentication once.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Email/password login",
)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Authenticate with email + password and return a :class:`TokenPair` (Req 1.1).

    Delegates authentication and lockout accounting to
    :meth:`AuthService.login_password`, which raises the generic,
    non-enumerating ``authentication_error`` for unknown email / bad password /
    non-active account (Req 1.2-1.4) and ``account_locked`` while a lock is in
    effect (Req 1.5). On success the authenticated user's claims are issued as
    a persisted token pair via :meth:`AuthService.issue_token_pair` (Task 6.2),
    so the refresh token is tracked for rotation/reuse-detection. The staged
    refresh row is committed by ``get_db`` on successful completion.
    """
    service = AuthService(session)
    user = await service.login_password(payload.email, payload.password)
    return service.issue_token_pair(user)


#: Fixed, non-enumerating acknowledgement returned by ``POST /auth/otp/request``
#: for every input. Whether the mobile is registered/active or not, the response
#: is identical so it never reveals account existence (Req 2.2).
_OTP_REQUEST_MESSAGE = "If the mobile number is registered, an OTP has been sent."


@router.post(
    "/otp/request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request an OTP for mobile login",
)
async def request_otp(
    payload: OtpRequest,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Request a one-time password for ``mobile`` (Req 2.1).

    Delegates to :meth:`AuthService.request_otp`, which generates and dispatches
    an OTP only for a registered, active mobile and silently ignores unknown or
    non-active numbers. This endpoint always responds with the same generic
    acknowledgement so the response never reveals whether the mobile exists
    (Req 2.2); genuine abuse still surfaces as a rate-limit error from the
    service (Req 2.4), reported through the central error envelope.
    """
    service = AuthService(session)
    await service.request_otp(payload.mobile)
    return {"message": _OTP_REQUEST_MESSAGE}


@router.post(
    "/otp/verify",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Verify an OTP and issue tokens",
)
async def verify_otp(
    payload: OtpVerifyRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Verify a submitted ``otp`` for ``mobile`` and return a :class:`TokenPair` (Req 2.5).

    Delegates verification to :meth:`AuthService.verify_otp`, which matches the
    stored OTP, invalidates it on success (so it cannot be reused), counts
    failures, and raises the generic authentication / expired-OTP errors on
    mismatch or expiry. On success the authenticated user's claims are issued as
    a persisted token pair via :meth:`AuthService.issue_token_pair` (Task 6.2);
    the staged refresh row is committed by ``get_db`` on success.
    """
    service = AuthService(session)
    user = await service.verify_otp(payload.mobile, payload.otp)
    return service.issue_token_pair(user)


@router.post(
    "/refresh",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Rotate a refresh token",
)
async def refresh(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Rotate a presented refresh token and return a fresh :class:`TokenPair` (Req 3.5).

    Delegates to :meth:`AuthService.refresh`, which verifies the presented
    token cryptographically, confirms it is unexpired and corresponds to a
    persisted, un-reused row, marks it used, and issues a successor in the same
    family (Req 3.5). Reuse of an already-used/revoked token revokes the whole
    family and raises the generic ``authentication_error``; invalid/expired
    tokens are likewise rejected without issuing (Req 3.7, 3.8). The staged
    rotation (marking the old row used, adding the successor, and any family
    revocation) is committed by ``get_db`` on successful completion.
    """
    service = AuthService(session)
    return await service.refresh(payload.refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token and its family",
)
async def logout(
    payload: LogoutRequest,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Revoke the presented refresh token and its entire family (Req 3.9).

    Delegates to :meth:`AuthService.logout`, which invalidates the presented
    token together with every token derived from the same issuance chain so
    none can be used for a subsequent refresh. A token that fails
    signature/expiry verification raises the generic ``authentication_error``
    (Req 3.7); a verified token with no persisted row is a quiet, idempotent
    no-op. The staged revocation is committed by ``get_db`` on success and the
    endpoint returns ``204 No Content``.
    """
    service = AuthService(session)
    await service.logout(payload.refresh_token)


__all__ = ["router"]

"""Impersonation lifecycle router (``/impersonation``) — Task 17.3.

Exposes the three lifecycle endpoints that let a superadmin or agencyadmin
start, end, and inspect an impersonation session (Req 11.4, 11.5):

* ``POST /impersonation/start`` — begin impersonating a target (exactly one of
  ``agency_id`` / ``customer_id``). Records the session and returns its
  indicator (Req 11.4).
* ``POST /impersonation/end`` — end the acting user's *current* active session,
  or no-op cleanly when none is active (Req 11.5).
* ``GET /impersonation/current`` — return the acting user's active-session
  indicator, or ``{"impersonating": false}`` when none.

All lifecycle logic — target-access validation (superadmin any / agencyadmin
only its accessible customers, Req 11.1-11.3), the single-active-session
invariant (Req 11.6), and 60-minute expiry (Req 11.7) — lives in
:class:`~app.services.impersonation_service.ImpersonationService`. This router
is thin wiring: resolve the acting impersonator, delegate, and shape the
response.

Acting impersonator
-------------------
The impersonator is always the **authenticated** user, resolved via the
:func:`app.api.deps.get_current_user` dependency, which reads
``request.state.tenant_context`` (attached by the auth/tenant middleware) and
loads the ``users`` row for ``tenant_context.user_id``. Because the context's
``user_id`` is the real signed-in user (not an impersonated identity),
impersonation is always initiated from the impersonator's own identity — full
interaction under an already-active impersonation context is Task 18. An
unauthenticated request has no context and is rejected fail-closed with
``tenant_context_missing`` (Req 9.8).

Authorization
-------------
These endpoints require only an authenticated user (a valid tenant context);
they are **not** gated by :func:`require_permission`, because impersonation is a
capability of the fixed roles rather than a module Action. The service enforces
who may impersonate whom (Req 11.1-11.3).

Errors — :class:`ImpersonationForbiddenError` (403),
:class:`ImpersonationActiveError` (409), and :class:`ValidationError` (422) —
propagate to the central exception handlers and are serialized into the standard
``{error:{code,message,details}}`` envelope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.impersonation import ImpersonationSession
from app.models.user import User
from app.schemas.impersonation import (
    ImpersonationEndRequest,
    ImpersonationIndicator,
    ImpersonationStartRequest,
)
from app.services.impersonation_service import ImpersonationService

# Single router for all /impersonation endpoints.
router = APIRouter(prefix="/impersonation", tags=["impersonation"])


def _indicator_from_session(
    service: ImpersonationService, session_row: ImpersonationSession
) -> ImpersonationIndicator:
    """Build the response indicator from a session row.

    Reuses :meth:`ImpersonationService.build_indicator` for the impersonated
    type/id/started_at, then adds the session ``id`` so callers can reference
    the specific session.
    """
    base = service.build_indicator(session_row)
    return ImpersonationIndicator(
        impersonating=True,
        impersonated_type=base["impersonated_type"],
        impersonated_id=base["impersonated_id"],
        session_id=session_row.id,
        started_at=session_row.started_at,
    )


@router.post(
    "/start",
    response_model=ImpersonationIndicator,
    status_code=status.HTTP_201_CREATED,
    summary="Start an impersonation session",
)
async def start_impersonation(
    payload: ImpersonationStartRequest,
    impersonator: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ImpersonationIndicator:
    """Start impersonating the requested target (Req 11.1-11.4, 11.6).

    Resolves the acting impersonator (the authenticated user) and delegates to
    :meth:`ImpersonationService.start`, which validates the exactly-one-target
    rule and the impersonator's access to the target (superadmin any /
    agencyadmin only its accessible customers), rejects a second concurrent
    session, and records the session with its start timestamp. Returns the
    created session's indicator (id, target type/id, started_at).

    Errors propagate to the central envelope:
    ``ImpersonationForbiddenError`` (403), ``ImpersonationActiveError`` (409),
    ``ValidationError`` (422).
    """
    service = ImpersonationService(session)
    session_row = await service.start(
        impersonator,
        agency_id=payload.agency_id,
        customer_id=payload.customer_id,
    )
    return _indicator_from_session(service, session_row)


@router.post(
    "/end",
    response_model=ImpersonationIndicator,
    status_code=status.HTTP_200_OK,
    summary="End the acting user's current impersonation session",
)
async def end_impersonation(
    payload: ImpersonationEndRequest | None = None,
    impersonator: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ImpersonationIndicator:
    """End the acting user's current active impersonation session (Req 11.5).

    Looks up the impersonator's current active session via
    :meth:`ImpersonationService.get_active` and, when present, ends it with
    :meth:`ImpersonationService.end` (stamping ``ended_at`` and marking it
    inactive). When there is no active session, this is a clean no-op.

    Returns ``200`` with the "not impersonating" indicator
    (``{"impersonating": false, ...}``) in both cases, so the frontend can
    uniformly clear its impersonation banner whether or not a session was
    actually active. The optional ``session_id`` in the body is advisory: the
    *current* active session is always the one ended, so a stale id can never
    end the wrong session.
    """
    service = ImpersonationService(session)
    active = await service.get_active(impersonator.id)
    if active is not None:
        await service.end(active.id)
    # No active session (or just ended it) → uniformly report not-impersonating.
    return ImpersonationIndicator.inactive()


@router.get(
    "/current",
    response_model=ImpersonationIndicator,
    status_code=status.HTTP_200_OK,
    summary="Get the acting user's current impersonation session",
)
async def current_impersonation(
    impersonator: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ImpersonationIndicator:
    """Return the acting user's active-session indicator (Req 11.4, 11.7).

    Delegates to :meth:`ImpersonationService.get_active`, which applies the
    60-minute expiry: a session older than the max age is treated as expired and
    ``None`` is returned. When a fresh active session exists its indicator is
    returned; otherwise ``{"impersonating": false, ...}``.
    """
    service = ImpersonationService(session)
    active = await service.get_active(impersonator.id)
    if active is None:
        return ImpersonationIndicator.inactive()
    return _indicator_from_session(service, active)


__all__ = ["router"]

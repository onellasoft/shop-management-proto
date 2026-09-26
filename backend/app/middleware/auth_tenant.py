"""Authentication + tenant middleware (Task 13.2 — Req 3.6, 9.1, 9.8).

This middleware runs before any route dependency and is responsible for
turning a bearer *access* token into the immutable
:class:`~app.core.tenant_context.TenantContext` that the per-route
:func:`app.api.deps.require_permission` dependency reads from
``request.state.tenant_context``.

Behavior
--------
For every incoming request the middleware:

1. Extracts the bearer token from the ``Authorization: Bearer <token>``
   header, if present.
2. When a token is present, decodes/verifies it via
   :func:`app.core.security.decode_access_token`. That helper already rejects a
   bad signature, an expired token, a wrong ``token_type``, or a malformed
   payload by raising :class:`~app.core.errors.AuthenticationError` (Req 3.6);
   this middleware does **not** re-implement JWT verification.
3. On a valid token, opens a short-lived async session (from the shared
   ``AsyncSessionLocal`` factory in :mod:`app.db.session` — the same engine/pool
   ``get_db`` uses) and calls
   :meth:`AuthorizationService.build_tenant_context` (Task 13.1) to derive the
   immutable :class:`TenantContext`, then attaches it to
   ``request.state.tenant_context`` for the request lifetime (Req 9.1). A
   non-superadmin whose scope cannot be derived raises
   :class:`~app.core.errors.TenantContextMissingError` (Req 9.8).

Public vs protected routes
--------------------------
Some routes must remain reachable *without* a token: ``GET /health``, the
``/auth`` endpoints (login, otp/request, otp/verify, refresh, logout), and the
OpenAPI/docs routes (``/docs``, ``/openapi.json``, ``/redoc``). Rather than
maintain a route allow-list, this middleware takes the simpler, fail-closed
stance:

* **No ``Authorization`` header** → the request is allowed through *without* a
  context. Public routes work because they need no context; protected routes
  still fail closed because :func:`app.api.deps.require_permission` (via
  ``_load_tenant_context``) raises
  :class:`~app.core.errors.TenantContextMissingError` when
  ``request.state.tenant_context`` is absent. This was confirmed against
  ``deps.py`` ``_load_tenant_context``, which returns the context or raises
  ``TenantContextMissingError`` — so auth is enforced at the dependency, not
  here.
* **An ``Authorization`` header IS present but the token is invalid/expired** →
  the request is rejected with the standard ``authentication_error`` envelope
  (Req 3.6), regardless of route. A caller presenting a broken token is always
  told so, even on an otherwise-public path.

Error envelope
--------------
Exception handlers registered by ``register_exception_handlers`` are installed
*inside* Starlette's application/exception middleware, which sits **below** a
``BaseHTTPMiddleware`` added via ``app.add_middleware``. An exception raised in
this middleware's ``dispatch`` therefore does **not** reach those handlers.
To keep the response shape identical, this middleware catches any
:class:`~app.core.errors.AppError` it raises (or that propagates from the
context build) and serializes it with the same ``{error:{code,message,details}}``
envelope via :meth:`AppError.to_dict`. This behavior is asserted by the tests
rather than assumed.

Impersonation (Task 18.1 — Req 12.1, 12.3, 12.4)
------------------------------------------------
After decoding the access token (which identifies the *real* / impersonator
user), the middleware looks up that impersonator's **active** impersonation
session via :meth:`ImpersonationService.get_active` on the *same* short-lived
session it uses to build the context. The authoritative source of an
impersonation is this active :class:`~app.models.impersonation.ImpersonationSession`
row (started through ``/impersonation/start``), **not** a client-supplied
header — a header alone never grants impersonation. (The design mentions an
``X-Impersonate-Tenant`` header as an alternative signal, but the active DB row
is authoritative and is what is used here.)

When ``get_active`` returns a session, it is passed to
:meth:`AuthorizationService.build_tenant_context`, which derives the
impersonated entity's boundary (``impersonating=True``, Req 12.1). Because
``get_active`` applies the 60-minute expiry (Req 11.7), an expired or ended
session returns ``None`` and the impersonator's *own* context is built — so
Req 12.4 (end/expiry restores the own context) is satisfied purely by
per-request detection, with no extra code.

Response indicator header contract (Req 12.3)
---------------------------------------------
While impersonating, the middleware attaches, to **every** response, discrete
headers derived from :meth:`ImpersonationService.build_indicator` so the
frontend can render the impersonation banner + exit control:

* ``X-Impersonating: true``
* ``X-Impersonated-Type``: ``customer`` or ``agency``
* ``X-Impersonated-Id``: the impersonated entity's UUID
* ``X-Impersonation``: a compact JSON of the full indicator payload

These headers are absent when the request is not impersonating. A response
header (rather than mutating every endpoint's body) keeps the indicator
uniform and endpoint-agnostic.
"""

from __future__ import annotations

import json

from fastapi.encoders import jsonable_encoder
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal
from app.services.authorization_service import AuthorizationService
from app.services.impersonation_service import ImpersonationService

_BEARER_PREFIX = "bearer "

# Response header names carrying the impersonation indicator (Req 12.3).
_HDR_IMPERSONATING = "X-Impersonating"
_HDR_IMPERSONATED_TYPE = "X-Impersonated-Type"
_HDR_IMPERSONATED_ID = "X-Impersonated-Id"
_HDR_IMPERSONATION_JSON = "X-Impersonation"


def _extract_bearer_token(request: Request) -> str | None:
    """Return the bearer token from the ``Authorization`` header, or ``None``.

    The scheme match is case-insensitive (``Bearer``/``bearer``). A header that
    is present but not a well-formed ``Bearer <token>`` value yields ``None``
    here; that empty/blank token then fails verification downstream, producing
    the standard authentication error (Req 3.6).
    """
    header = request.headers.get("Authorization")
    if not header:
        return None
    if not header.lower().startswith(_BEARER_PREFIX):
        return None
    return header[len(_BEARER_PREFIX):].strip()


def _attach_impersonation_headers(response: Response, indicator: dict) -> None:
    """Attach the impersonation indicator headers to ``response`` (Req 12.3).

    Sets the discrete ``X-Impersonating`` / ``X-Impersonated-Type`` /
    ``X-Impersonated-Id`` headers plus the compact-JSON ``X-Impersonation``
    header from the :meth:`ImpersonationService.build_indicator` payload. Header
    values are always strings; ``None`` fields (e.g. a missing ``started_at``)
    are dropped from the discrete headers but preserved in the JSON payload.
    """
    response.headers[_HDR_IMPERSONATING] = "true"
    impersonated_type = indicator.get("impersonated_type")
    if impersonated_type is not None:
        response.headers[_HDR_IMPERSONATED_TYPE] = str(impersonated_type)
    impersonated_id = indicator.get("impersonated_id")
    if impersonated_id is not None:
        response.headers[_HDR_IMPERSONATED_ID] = str(impersonated_id)
    # Compact JSON (no spaces) keeps the header value small and header-safe.
    response.headers[_HDR_IMPERSONATION_JSON] = json.dumps(
        indicator, separators=(",", ":")
    )


class AuthTenantMiddleware(BaseHTTPMiddleware):
    """Attach a :class:`TenantContext` to authenticated requests (Req 9.1).

    See the module docstring for the public/protected route policy and the
    error-envelope handling.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        token = _extract_bearer_token(request)

        # No credentials presented: let the request through without a context.
        # Public routes need none; protected routes fail closed at the
        # require_permission dependency (TenantContextMissingError).
        if token is None:
            return await call_next(request)

        # The impersonation indicator built for this request (Req 12.3), if any;
        # attached to the response after call_next below.
        indicator: dict | None = None

        try:
            # decode_access_token raises AuthenticationError on bad signature,
            # expiry, wrong token_type, or malformed payload (Req 3.6). We do
            # not re-implement any of that here.
            claims = decode_access_token(token)

            # Build the context using a short-lived session from the SAME
            # factory/engine get_db uses (app.db.session.AsyncSessionLocal), so
            # no second engine/pool is created. The impersonation lookup and the
            # context build share this one session/transaction.
            async with AsyncSessionLocal() as session:
                # --- Impersonation detection (Task 18.1 — Req 12.1) ---------
                # The authoritative signal is the impersonator's ACTIVE session
                # row (started via /impersonation/start), NOT a client header.
                # get_active applies the 60-min expiry (Req 11.7): an expired or
                # ended session returns None, so the impersonator's own context
                # is built and Req 12.4 (restore own context) holds with no
                # extra code here.
                impersonation = await ImpersonationService(session).get_active(
                    claims.sub
                )

                authz = AuthorizationService(session)
                context = await authz.build_tenant_context(
                    claims, impersonation=impersonation
                )

                # Build the response indicator while the (session-bound) row is
                # still available. build_indicator reads only plain attributes.
                if impersonation is not None:
                    indicator = ImpersonationService(session).build_indicator(
                        impersonation
                    )

            request.state.tenant_context = context
        except AppError as exc:
            # Handlers registered on the app do not catch exceptions raised in
            # a BaseHTTPMiddleware, so serialize the standard envelope here to
            # keep the response shape identical (Req 3.6, 9.8).
            return JSONResponse(
                status_code=exc.http_status,
                content=jsonable_encoder(exc.to_dict()),
            )

        response = await call_next(request)

        # Req 12.3 — while impersonating, every response carries the indicator
        # so the frontend can render the banner + exit control.
        if indicator is not None:
            _attach_impersonation_headers(response, indicator)

        return response


__all__ = ["AuthTenantMiddleware"]

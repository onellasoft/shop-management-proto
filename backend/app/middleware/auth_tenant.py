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

Impersonation
-------------
Impersonation detection (the ``X-Impersonate-Tenant`` header / active session)
is Task 18 and is intentionally **not** implemented here — see the clearly
marked extension point below. This task builds only the non-impersonation
context.
"""

from __future__ import annotations

from fastapi.encoders import jsonable_encoder
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal
from app.services.authorization_service import AuthorizationService

_BEARER_PREFIX = "bearer "


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

        try:
            # decode_access_token raises AuthenticationError on bad signature,
            # expiry, wrong token_type, or malformed payload (Req 3.6). We do
            # not re-implement any of that here.
            claims = decode_access_token(token)

            # --- Impersonation extension point (Task 18) --------------------
            # Task 18.1 will detect impersonation here (X-Impersonate-Tenant
            # header / active session) and pass the resolved impersonation
            # state to build_tenant_context. This task builds only the
            # non-impersonation context.
            # ----------------------------------------------------------------

            # Build the context using a short-lived session from the SAME
            # factory/engine get_db uses (app.db.session.AsyncSessionLocal), so
            # no second engine/pool is created. The build only reads
            # (customers / customer_users); commit is unnecessary but harmless.
            async with AsyncSessionLocal() as session:
                authz = AuthorizationService(session)
                context = await authz.build_tenant_context(claims)

            request.state.tenant_context = context
        except AppError as exc:
            # Handlers registered on the app do not catch exceptions raised in
            # a BaseHTTPMiddleware, so serialize the standard envelope here to
            # keep the response shape identical (Req 3.6, 9.8).
            return JSONResponse(
                status_code=exc.http_status,
                content=jsonable_encoder(exc.to_dict()),
            )

        return await call_next(request)


__all__ = ["AuthTenantMiddleware"]

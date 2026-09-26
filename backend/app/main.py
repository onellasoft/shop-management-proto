"""FastAPI application factory.

Builds and configures the Onella backend application. Responsibilities kept
here at the foundation stage:

* Instantiate the :class:`~fastapi.FastAPI` app with project metadata.
* Register the standardized exception handlers from ``app.core.errors`` so
  every route returns the ``{error:{code,message,details}}`` envelope.
* Expose a lightweight ``GET /health`` route used to confirm the app boots and
  to back liveness/readiness probes.

Routers, middleware (auth/tenant), and other wiring are added by later tasks;
this module is intentionally the single composition root they plug into.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth as auth_router
from app.api.routers import impersonation as impersonation_router
from app.api.routers import modules as modules_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.middleware.auth_tenant import AuthTenantMiddleware


def create_app() -> FastAPI:
    """Create and configure a FastAPI application instance.

    Returns a fully-wired app so tests and the ASGI server share identical
    setup. Additional routers/middleware are registered here as later tasks
    introduce them.
    """
    app = FastAPI(
        title="Onella Backend",
        version="0.1.0",
        description=(
            "Async FastAPI service providing authentication, RBAC, "
            "multi-tenancy, impersonation, and audit logging."
        ),
        debug=settings.is_development,
    )

    # Auth + tenant middleware (Task 13.2, Req 3.6/9.1/9.8): decodes the bearer
    # access token and attaches the immutable TenantContext to request.state so
    # the per-route require_permission dependency can read it. It is added
    # before CORS below so that CORS remains the outermost middleware and adds
    # its headers even to the auth error envelope this middleware may return.
    # Starlette runs the most-recently-added middleware outermost, so this runs
    # after CORS but still before route dependencies execute.
    app.add_middleware(AuthTenantMiddleware)

    # CORS: allow the frontend origin(s) to call the API from the browser.
    # In production the frontend is served same-origin behind nginx and proxies
    # /api to the backend, so CORS is primarily a development convenience.
    allow_all = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if allow_all else settings.cors_origins,
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Standardized error envelope for all routes.
    register_exception_handlers(app)

    # Authentication routes (login now; OTP/refresh/logout added by later tasks
    # onto the same router).
    app.include_router(auth_router.router)

    # Module catalog + subscription management (Task 10.3, Req 8.3).
    app.include_router(modules_router.router)

    # Impersonation session lifecycle (Task 17.3, Req 11.4/11.5).
    app.include_router(impersonation_router.router)

    # Health check to confirm the app boots and is serving requests.
    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Liveness probe. Returns ``{"status": "ok"}`` when the app is up."""
        return {"status": "ok"}

    return app


# Module-level ASGI app for ``uvicorn app.main:app``.
app = create_app()

__all__ = ["create_app", "app"]

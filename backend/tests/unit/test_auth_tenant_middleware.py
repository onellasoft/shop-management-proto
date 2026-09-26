"""Unit/integration tests for the auth + tenant middleware (Task 13.2).

Exercises the middleware wired into a real FastAPI app via Starlette's
``TestClient``, covering the public-vs-protected route policy, the standard
error envelope on a bad token, and successful ``TenantContext`` attachment
(Req 3.6, 9.1, 9.8).

The database is not touched: the middleware builds the context through
``AuthorizationService.build_tenant_context`` over a session from
``app.db.session.AsyncSessionLocal``. Both are replaced with in-memory fakes
(a no-op async session and a stub build) so the middleware's request handling
runs without a live Postgres — mirroring how
``tests/unit/test_authorization_service_build_context.py`` fakes the session.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import Depends, Request
from starlette.testclient import TestClient

import app.middleware.auth_tenant as mw
from app.api.deps import require_permission
from app.core.security import create_access_token
from app.core.tenant_context import TenantContext
from app.main import create_app


# ---------------------------------------------------------------------------
# Fakes: a no-op async session context manager so the middleware never opens a
# real DB connection when building the context.
# ---------------------------------------------------------------------------


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _noop_session_factory():
    return _NoopSession()


def _context(role_type: str = "customeradmin") -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
        role_type=role_type,
        agency_scope=None,
        customer_scope=frozenset({uuid4()}),
        is_superadmin=(role_type == "superadmin"),
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _build_app_with_probe():
    """Create the real app plus a test-only protected route.

    The probe route depends on :func:`require_permission`, which returns the
    attached :class:`TenantContext`; the route echoes the derived role/scope so
    tests can assert what the endpoint actually saw.
    """
    app = create_app()

    @app.get("/_probe/protected")
    async def _protected(
        ctx=Depends(require_permission("modules.catalog.catalog.read")),
    ):
        return {
            "role_type": ctx.role_type,
            "is_superadmin": ctx.is_superadmin,
            "customer_scope": [str(c) for c in ctx.customer_scope],
        }

    # A probe that reads the context straight off request.state, used to assert
    # what the middleware attached without routing through require_permission's
    # DB-backed permission/module checks (covered by their own tests).
    @app.get("/_probe/context")
    async def _context_probe(request: Request):
        ctx = getattr(request.state, "tenant_context", None)
        if ctx is None:
            return {"context": None}
        return {
            "role_type": ctx.role_type,
            "is_superadmin": ctx.is_superadmin,
            "customer_scope": [str(c) for c in ctx.customer_scope],
        }

    return app


# ---------------------------------------------------------------------------
# Public routes are reachable without a token
# ---------------------------------------------------------------------------


def test_health_is_public_without_token():
    client = TestClient(_build_app_with_probe())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_auth_route_is_reachable_without_token(monkeypatch):
    # The /auth/login route must not be blocked by the middleware when no
    # bearer token is sent. It reaches the endpoint (which then hits the DB /
    # service). We only assert the middleware did NOT short-circuit it with an
    # auth envelope: a missing-token request is NOT a 401 authentication_error.
    client = TestClient(_build_app_with_probe(), raise_server_exceptions=False)
    resp = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "x"}
    )
    # Whatever the downstream outcome, it is not the middleware's bearer-token
    # rejection (401 authentication_error), proving the route stayed public.
    if resp.status_code == 401:
        assert resp.json()["error"]["code"] != "authentication_error"


# ---------------------------------------------------------------------------
# Protected route without a token → dependency fails closed
# ---------------------------------------------------------------------------


def test_protected_route_without_token_is_rejected_by_dependency():
    client = TestClient(_build_app_with_probe())
    resp = client.get("/_probe/protected")
    # No Authorization header → middleware passes through with no context →
    # require_permission's _load_tenant_context raises TenantContextMissingError
    # (Req 9.8), surfaced by the registered handler as a 403 envelope.
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"


# ---------------------------------------------------------------------------
# Protected route with an invalid/expired token → 401 auth envelope
# ---------------------------------------------------------------------------


def test_malformed_token_returns_authentication_envelope():
    client = TestClient(_build_app_with_probe())
    resp = client.get(
        "/_probe/protected",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "authentication_error"
    assert set(body["error"].keys()) == {"code", "message", "details"}


def test_bad_token_on_public_route_still_rejected():
    # An Authorization header that IS present but invalid is rejected even on an
    # otherwise-public path (Req 3.6).
    client = TestClient(_build_app_with_probe())
    resp = client.get("/health", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_error"


# ---------------------------------------------------------------------------
# Valid token → TenantContext populated and seen by the route
# ---------------------------------------------------------------------------


def test_valid_token_populates_tenant_context(monkeypatch):
    ctx = _context(role_type="customeradmin")

    # Avoid opening a real DB session; the stubbed build ignores it anyway.
    monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

    async def _fake_build(self, claims, impersonation=None, **kwargs):
        # The middleware must decode a real token before reaching here; assert
        # the claims flowed through with the expected role.
        assert claims.role_type == "customeradmin"
        return ctx

    monkeypatch.setattr(
        mw.AuthorizationService, "build_tenant_context", _fake_build
    )

    token = create_access_token(
        user_id=ctx.user_id, role_type="customeradmin", email="u@example.com"
    )
    client = TestClient(_build_app_with_probe())
    # Read the attached context directly off request.state to isolate the
    # middleware's behavior from require_permission's DB-backed checks.
    resp = client.get(
        "/_probe/context", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["role_type"] == "customeradmin"
    assert data["is_superadmin"] is False
    assert data["customer_scope"] == [str(next(iter(ctx.customer_scope)))]


def test_context_build_rejection_surfaces_envelope(monkeypatch):
    # A valid token whose scope cannot be derived (build raises
    # TenantContextMissingError, Req 9.8) is serialized by the middleware into
    # the standard envelope even though it is raised inside the middleware.
    from app.core.errors import TenantContextMissingError

    monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

    async def _fail_build(self, claims, impersonation=None, **kwargs):
        raise TenantContextMissingError(details={"reason": "customeradmin_no_customers"})

    monkeypatch.setattr(
        mw.AuthorizationService, "build_tenant_context", _fail_build
    )

    token = create_access_token(
        user_id=uuid4(), role_type="customeradmin", email="u@example.com"
    )
    client = TestClient(_build_app_with_probe())
    resp = client.get(
        "/_probe/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"

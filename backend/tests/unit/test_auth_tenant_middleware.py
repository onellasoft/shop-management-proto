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

import json
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, Request
from starlette.testclient import TestClient

import app.middleware.auth_tenant as mw
from app.api.deps import require_permission
from app.core.security import create_access_token
from app.core.tenant_context import TenantContext
from app.main import create_app
from app.services.impersonation_service import ImpersonationService


# ---------------------------------------------------------------------------
# Fakes: a no-op async session context manager so the middleware never opens a
# real DB connection when building the context.
# ---------------------------------------------------------------------------


class _EmptyResult:
    def scalar_one_or_none(self):
        return None


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):  # noqa: ANN001
        # The middleware runs ImpersonationService.get_active on this session
        # before building the context. Returning an empty result models "no
        # active impersonation" so tests that don't stub get_active still see
        # the impersonator's own context.
        return _EmptyResult()


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


def _impersonated_context(
    *, impersonator: UUID, impersonated_customer: UUID
) -> TenantContext:
    return TenantContext(
        user_id=impersonator,
        role_type="superadmin",
        agency_scope=None,
        customer_scope=frozenset({impersonated_customer}),
        is_superadmin=False,
        impersonating=True,
        impersonated_agency_id=None,
        impersonated_customer_id=impersonated_customer,
        impersonator_user_id=impersonator,
        custom_role_customer_id=None,
    )


class _FakeImpersonationSession:
    """Stand-in for an active ImpersonationSession row (customer target)."""

    def __init__(self, *, impersonated_customer_id: UUID) -> None:
        self.impersonated_agency_id = None
        self.impersonated_customer_id = impersonated_customer_id
        self.impersonator_user_id = uuid4()
        self.started_at = None


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
            "impersonating": ctx.impersonating,
            "impersonated_customer_id": (
                str(ctx.impersonated_customer_id)
                if ctx.impersonated_customer_id is not None
                else None
            ),
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


# ---------------------------------------------------------------------------
# Impersonation (Task 18.1 — Req 12.1, 12.3, 12.4)
# ---------------------------------------------------------------------------


def test_active_impersonation_attaches_impersonated_context_and_headers(
    monkeypatch,
):
    # Req 12.1/12.3 — when get_active returns a session, the attached context is
    # impersonating (built from the impersonated entity) and the response
    # carries the impersonation indicator headers.
    impersonator = uuid4()
    impersonated_customer = uuid4()
    ctx = _impersonated_context(
        impersonator=impersonator, impersonated_customer=impersonated_customer
    )
    fake_session_row = _FakeImpersonationSession(
        impersonated_customer_id=impersonated_customer
    )

    monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

    async def _fake_get_active(self, impersonator_id):
        # Detection keys off the real (impersonator) user id from the token.
        assert impersonator_id == impersonator
        return fake_session_row

    def _fake_build_indicator(self, session):
        assert session is fake_session_row
        return {
            "impersonating": True,
            "impersonated_type": "customer",
            "impersonated_id": str(impersonated_customer),
            "started_at": None,
        }

    async def _fake_build(self, claims, impersonation=None, **kwargs):
        # The active session must be threaded into build_tenant_context.
        assert impersonation is fake_session_row
        return ctx

    monkeypatch.setattr(ImpersonationService, "get_active", _fake_get_active)
    monkeypatch.setattr(
        ImpersonationService, "build_indicator", _fake_build_indicator
    )
    monkeypatch.setattr(
        mw.AuthorizationService, "build_tenant_context", _fake_build
    )

    token = create_access_token(
        user_id=impersonator, role_type="superadmin", email="s@example.com"
    )
    client = TestClient(_build_app_with_probe())
    resp = client.get(
        "/_probe/context", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["impersonating"] is True
    assert data["impersonated_customer_id"] == str(impersonated_customer)
    assert data["customer_scope"] == [str(impersonated_customer)]

    # Req 12.3 — indicator headers present on the response.
    assert resp.headers["X-Impersonating"] == "true"
    assert resp.headers["X-Impersonated-Type"] == "customer"
    assert resp.headers["X-Impersonated-Id"] == str(impersonated_customer)
    payload = json.loads(resp.headers["X-Impersonation"])
    assert payload["impersonating"] is True
    assert payload["impersonated_id"] == str(impersonated_customer)


def test_no_active_impersonation_uses_own_context_without_headers(monkeypatch):
    # Req 12.4 — when get_active returns None (ended/expired/none), the context
    # is the impersonator's own and no indicator header is present.
    ctx = _context(role_type="customeradmin")

    monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

    async def _fake_get_active(self, impersonator_id):
        return None

    async def _fake_build(self, claims, impersonation=None, **kwargs):
        assert impersonation is None
        return ctx

    monkeypatch.setattr(ImpersonationService, "get_active", _fake_get_active)
    monkeypatch.setattr(
        mw.AuthorizationService, "build_tenant_context", _fake_build
    )

    token = create_access_token(
        user_id=ctx.user_id, role_type="customeradmin", email="u@example.com"
    )
    client = TestClient(_build_app_with_probe())
    resp = client.get(
        "/_probe/context", headers={"Authorization": f"Bearer {token}"}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["impersonating"] is False
    assert "X-Impersonating" not in resp.headers
    assert "X-Impersonation" not in resp.headers
    assert "X-Impersonated-Type" not in resp.headers
    assert "X-Impersonated-Id" not in resp.headers

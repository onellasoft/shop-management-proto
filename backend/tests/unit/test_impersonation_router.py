"""Router tests for the impersonation lifecycle endpoints (Task 17.3).

Exercises ``/impersonation/{start,end,current}`` wired into the real FastAPI app
through Starlette's ``TestClient``. The focus is *wiring*, not re-testing the
service (Task 17.2 covers the lifecycle semantics), so:

* the auth/tenant middleware is stubbed (as in
  ``test_auth_tenant_middleware.py``) to attach a chosen
  :class:`TenantContext` for a valid bearer token, without touching Postgres;
* ``get_db`` is overridden with an in-memory fake session whose ``get`` returns
  the acting :class:`User` (what :func:`get_current_user` loads);
* :class:`ImpersonationService` methods are monkeypatched so we can assert the
  router resolves the acting impersonator, delegates correctly, shapes the
  response, and propagates domain errors to the standard envelope.

Covers Req 11.4 (start records/returns the session), 11.5 (end the current
active session; clean no-op when none), the forbidden/active/validation error
envelopes, and the unauthenticated rejection (Req 9.8).
"""

from __future__ import annotations

import datetime
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

import app.api.routers.impersonation as router_mod
import app.middleware.auth_tenant as mw
from app.core.errors import (
    ImpersonationActiveError,
    ImpersonationForbiddenError,
    ValidationError,
)
from app.core.security import create_access_token
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.main import create_app
from app.models.impersonation import ImpersonationSession
from app.models.user import User

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class _EmptyResult:
    def scalar_one_or_none(self):
        return None


class _NoopSession:
    """No-op async session context manager for the middleware's context build."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):  # noqa: ANN001
        # The middleware runs ImpersonationService.get_active on this session
        # before building the context (Task 18.1). Return an empty result so
        # the impersonator has no active session and their own context is used.
        return _EmptyResult()


def _noop_session_factory():
    return _NoopSession()


class _FakeDBSession:
    """Minimal fake for the request DB session used by ``get_current_user``.

    Only ``get(User, id)`` is exercised by the router path under test.
    """

    def __init__(self, user: User | None):
        self._user = user

    async def get(self, model, pk):
        assert model is User
        return self._user


def _user(role_type: str = "superadmin", agency_id=None) -> User:
    u = User(role_type=role_type, agency_id=agency_id)
    u.id = uuid4()
    return u


def _context_for(user: User) -> TenantContext:
    return TenantContext(
        user_id=user.id,
        role_type=user.role_type,
        agency_scope=None,
        customer_scope=frozenset(),
        is_superadmin=(user.role_type == "superadmin"),
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _session_row(customer_id=None, agency_id=None) -> ImpersonationSession:
    row = ImpersonationSession(
        impersonator_user_id=uuid4(),
        impersonated_agency_id=agency_id,
        impersonated_customer_id=customer_id,
        active=True,
        started_at=datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
    )
    row.id = uuid4()
    return row


@pytest.fixture
def wired(monkeypatch):
    """Build an app with a stubbed authenticated user and fake DB session.

    Returns ``(client, user, token)``. The auth middleware is stubbed to attach
    ``user``'s context for the returned bearer token, and ``get_db`` yields a
    fake session whose ``get`` returns ``user``.
    """
    user = _user(role_type="superadmin")
    ctx = _context_for(user)

    # Stub the middleware's context build so a valid token attaches ctx without
    # touching Postgres (mirrors test_auth_tenant_middleware.py).
    monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

    async def _fake_build(self, claims, impersonation=None, **kwargs):
        return ctx

    monkeypatch.setattr(mw.AuthorizationService, "build_tenant_context", _fake_build)

    app = create_app()

    async def _override_get_db():
        yield _FakeDBSession(user)

    app.dependency_overrides[get_db] = _override_get_db

    token = create_access_token(
        user_id=user.id, role_type=user.role_type, email="admin@example.com"
    )
    client = TestClient(app)
    return client, user, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_returns_indicator_for_valid_context(wired, monkeypatch):
    client, user, token = wired
    customer_id = uuid4()
    row = _session_row(customer_id=customer_id)

    captured = {}

    async def _fake_start(self, impersonator, agency_id=None, customer_id=None):
        captured["impersonator_id"] = impersonator.id
        captured["agency_id"] = agency_id
        captured["customer_id"] = customer_id
        return row

    monkeypatch.setattr(router_mod.ImpersonationService, "start", _fake_start)

    resp = client.post(
        "/impersonation/start",
        json={"customer_id": str(customer_id)},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["impersonating"] is True
    assert body["impersonated_type"] == "customer"
    assert body["impersonated_id"] == str(customer_id)
    assert body["session_id"] == str(row.id)
    assert body["started_at"] is not None
    # Router resolved the acting impersonator (authenticated user) and forwarded
    # the target unchanged.
    assert captured["impersonator_id"] == user.id
    assert captured["customer_id"] == customer_id
    assert captured["agency_id"] is None


def test_start_propagates_forbidden_as_403_envelope(wired, monkeypatch):
    client, _user, token = wired

    async def _forbidden(self, impersonator, agency_id=None, customer_id=None):
        raise ImpersonationForbiddenError(details={"reason": "out_of_scope"})

    monkeypatch.setattr(router_mod.ImpersonationService, "start", _forbidden)

    resp = client.post(
        "/impersonation/start",
        json={"customer_id": str(uuid4())},
        headers=_auth(token),
    )

    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "impersonation_forbidden"
    assert set(body["error"].keys()) == {"code", "message", "details"}


def test_start_propagates_active_session_as_409_envelope(wired, monkeypatch):
    client, _user, token = wired

    async def _active(self, impersonator, agency_id=None, customer_id=None):
        raise ImpersonationActiveError()

    monkeypatch.setattr(router_mod.ImpersonationService, "start", _active)

    resp = client.post(
        "/impersonation/start",
        json={"customer_id": str(uuid4())},
        headers=_auth(token),
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "impersonation_active"


def test_start_rejects_neither_target_via_schema(wired):
    client, _user, token = wired
    resp = client.post("/impersonation/start", json={}, headers=_auth(token))
    # The request schema's XOR validator rejects neither/both before the service
    # is called → FastAPI 422 request-validation error.
    assert resp.status_code == 422


def test_start_rejects_both_targets_via_schema(wired):
    client, _user, token = wired
    resp = client.post(
        "/impersonation/start",
        json={"agency_id": str(uuid4()), "customer_id": str(uuid4())},
        headers=_auth(token),
    )
    assert resp.status_code == 422


def test_start_propagates_service_validation_error_envelope(wired, monkeypatch):
    # Even if a payload slips past the schema, a ValidationError raised by the
    # service surfaces as the standard envelope.
    client, _user, token = wired

    async def _invalid(self, impersonator, agency_id=None, customer_id=None):
        raise ValidationError("bad target")

    monkeypatch.setattr(router_mod.ImpersonationService, "start", _invalid)

    resp = client.post(
        "/impersonation/start",
        json={"customer_id": str(uuid4())},
        headers=_auth(token),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# end
# ---------------------------------------------------------------------------


def test_end_ends_current_active_session(wired, monkeypatch):
    client, user, token = wired
    active = _session_row(customer_id=uuid4())
    active.impersonator_user_id = user.id

    ended = {}

    async def _get_active(self, impersonator_id):
        assert impersonator_id == user.id
        return active

    async def _end(self, session_id):
        ended["session_id"] = session_id

    monkeypatch.setattr(router_mod.ImpersonationService, "get_active", _get_active)
    monkeypatch.setattr(router_mod.ImpersonationService, "end", _end)

    resp = client.post("/impersonation/end", json={}, headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json() == {
        "impersonating": False,
        "impersonated_type": None,
        "impersonated_id": None,
        "session_id": None,
        "started_at": None,
    }
    # The router ended the CURRENT active session (looked up by impersonator).
    assert ended["session_id"] == active.id


def test_end_with_no_active_session_is_clean_noop(wired, monkeypatch):
    client, _user, token = wired
    calls = {"end": 0}

    async def _get_active(self, impersonator_id):
        return None

    async def _end(self, session_id):
        calls["end"] += 1

    monkeypatch.setattr(router_mod.ImpersonationService, "get_active", _get_active)
    monkeypatch.setattr(router_mod.ImpersonationService, "end", _end)

    resp = client.post("/impersonation/end", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json()["impersonating"] is False
    # No active session → end is never called (clean no-op).
    assert calls["end"] == 0


# ---------------------------------------------------------------------------
# current
# ---------------------------------------------------------------------------


def test_current_returns_indicator_when_active(wired, monkeypatch):
    client, user, token = wired
    active = _session_row(agency_id=uuid4())

    async def _get_active(self, impersonator_id):
        assert impersonator_id == user.id
        return active

    monkeypatch.setattr(router_mod.ImpersonationService, "get_active", _get_active)

    resp = client.get("/impersonation/current", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["impersonating"] is True
    assert body["impersonated_type"] == "agency"
    assert body["impersonated_id"] == str(active.impersonated_agency_id)
    assert body["session_id"] == str(active.id)


def test_current_returns_false_when_no_active_session(wired, monkeypatch):
    client, _user, token = wired

    async def _get_active(self, impersonator_id):
        return None

    monkeypatch.setattr(router_mod.ImpersonationService, "get_active", _get_active)

    resp = client.get("/impersonation/current", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json()["impersonating"] is False
    assert resp.json()["impersonated_id"] is None


# ---------------------------------------------------------------------------
# unauthenticated
# ---------------------------------------------------------------------------


def test_unauthenticated_request_is_rejected():
    # No bearer token → no tenant context attached → get_current_user fails
    # closed with tenant_context_missing (Req 9.8).
    app = create_app()
    client = TestClient(app)
    resp = client.get("/impersonation/current")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"

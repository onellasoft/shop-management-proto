"""Router tests for the audit query/export endpoints (Task 22.3).

Exercises ``GET /audit/logs`` and ``GET /audit/logs/export`` wired into the real
FastAPI app through Starlette's ``TestClient``. The focus is *wiring* — that the
endpoints resolve the requester's :class:`TenantContext`, delegate to
:class:`AuditService`, shape the response (paginated JSON / downloadable file
with the right media type + Content-Disposition), and reject unauthenticated
requests (Req 15.1, 15.6, 9.8). Service semantics are covered by the service
tests.

The auth/tenant middleware is stubbed (as in ``test_impersonation_router.py``)
so a valid bearer token attaches a chosen context without touching Postgres, and
``get_db`` is overridden with a no-op session; :class:`AuditService` methods are
monkeypatched so the router logic is tested in isolation.
"""

from __future__ import annotations

import datetime
import json
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

import app.api.routers.audit as router_mod
import app.middleware.auth_tenant as mw
from app.core.errors import InvalidDateRangeError
from app.core.security import create_access_token
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.main import create_app
from app.models.audit import AuditLog
from app.services.audit_service import Page

UTC = datetime.timezone.utc


class _EmptyResult:
    def scalar_one_or_none(self):
        return None


class _NoopSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):  # noqa: ANN001
        return _EmptyResult()


def _noop_session_factory():
    return _NoopSession()


class _FakeDBSession:
    """Minimal request DB session; the audit endpoints never touch it directly
    (the service is stubbed), so it only needs to exist as the get_db yield."""


def _context() -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
        role_type="superadmin",
        agency_scope=None,
        customer_scope=frozenset(),
        is_superadmin=True,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _log() -> AuditLog:
    row = AuditLog(
        user_id=uuid4(),
        role_type="customeradmin",
        agency_id=uuid4(),
        customer_id=uuid4(),
        module="marketing",
        sub_module="campaign",
        resource="MessageTemplate",
        action="create",
        old_value=None,
        new_value={"name": "x"},
        impersonation=False,
        impersonator_user_id=None,
        created_at=datetime.datetime(2024, 1, 1, tzinfo=UTC),
    )
    row.id = uuid4()
    return row


@pytest.fixture
def wired(monkeypatch):
    """App with a stubbed authenticated context and a no-op DB session.

    Returns ``(client, ctx, token)``.
    """
    ctx = _context()

    monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

    async def _fake_build(self, claims, impersonation=None, **kwargs):
        return ctx

    monkeypatch.setattr(mw.AuthorizationService, "build_tenant_context", _fake_build)

    app = create_app()

    async def _override_get_db():
        yield _FakeDBSession()

    app.dependency_overrides[get_db] = _override_get_db

    token = create_access_token(
        user_id=ctx.user_id, role_type=ctx.role_type, email="admin@example.com"
    )
    return TestClient(app), ctx, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# GET /audit/logs
# ---------------------------------------------------------------------------


def test_query_returns_paginated_results(wired, monkeypatch):
    client, ctx, token = wired
    row = _log()
    captured = {}

    async def _fake_query(self, context, filters=None, *, page=1, page_size=50):
        captured["ctx"] = context
        captured["filters"] = filters
        captured["page"] = page
        captured["page_size"] = page_size
        return Page(items=[row], page=page, page_size=page_size, total=1)

    monkeypatch.setattr(router_mod.AuditService, "query", _fake_query)

    resp = client.get(
        "/audit/logs",
        params={"page": 2, "page_size": 10, "action": "create"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["page"] == 2
    assert body["page_size"] == 10
    assert body["total"] == 1
    assert body["has_more"] is False
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(row.id)
    assert body["items"][0]["action"] == "create"
    # Router resolved the authenticated context and forwarded the filter.
    assert captured["ctx"].user_id == ctx.user_id
    assert captured["filters"].action == "create"
    assert captured["page"] == 2


def test_query_propagates_invalid_date_range_envelope(wired, monkeypatch):
    client, _ctx, token = wired

    async def _bad(self, context, filters=None, *, page=1, page_size=50):
        raise InvalidDateRangeError(details={"reason": "start_after_end"})

    monkeypatch.setattr(router_mod.AuditService, "query", _bad)

    resp = client.get(
        "/audit/logs",
        params={
            "date_from": "2024-09-01T00:00:00+00:00",
            "date_to": "2024-03-01T00:00:00+00:00",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_date_range"


def test_query_rejects_page_below_one_via_validation(wired):
    client, _ctx, token = wired
    resp = client.get("/audit/logs", params={"page": 0}, headers=_auth(token))
    # Query param constraint ge=1 → FastAPI 422 request validation error.
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /audit/logs/export
# ---------------------------------------------------------------------------


def test_export_csv_returns_downloadable_file(wired, monkeypatch):
    client, _ctx, token = wired
    captured = {}

    async def _fake_export(self, context, filters=None, fmt="csv"):
        captured["fmt"] = fmt
        return b"id,action\n1,create\n"

    monkeypatch.setattr(router_mod.AuditService, "export", _fake_export)

    resp = client.get(
        "/audit/logs/export", params={"format": "csv"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert "audit_logs.csv" in resp.headers["content-disposition"]
    assert resp.content == b"id,action\n1,create\n"
    assert captured["fmt"] == "csv"


def test_export_json_returns_downloadable_file(wired, monkeypatch):
    client, _ctx, token = wired

    async def _fake_export(self, context, filters=None, fmt="csv"):
        return json.dumps([{"id": "1", "action": "create"}]).encode("utf-8")

    monkeypatch.setattr(router_mod.AuditService, "export", _fake_export)

    resp = client.get(
        "/audit/logs/export", params={"format": "json"}, headers=_auth(token)
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "audit_logs.json" in resp.headers["content-disposition"]
    assert json.loads(resp.content) == [{"id": "1", "action": "create"}]


def test_export_rejects_unknown_format_via_validation(wired):
    client, _ctx, token = wired
    resp = client.get(
        "/audit/logs/export", params={"format": "xml"}, headers=_auth(token)
    )
    # Literal["csv","json"] query param → 422 for an out-of-set value.
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Unauthenticated
# ---------------------------------------------------------------------------


def test_query_unauthenticated_is_rejected():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/audit/logs")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"


def test_export_unauthenticated_is_rejected():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/audit/logs/export")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"

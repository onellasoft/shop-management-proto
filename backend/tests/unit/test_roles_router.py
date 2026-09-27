"""Router tests for the role management endpoints (Task 11.3).

Exercises ``/roles/*`` and ``/permissions/tree`` wired into the real FastAPI app
through Starlette's ``TestClient``. The focus is *wiring*, not re-testing the
service (Tasks 11.1-11.2 cover the service logic), so:

* the auth/tenant middleware is stubbed (as in
  ``test_impersonation_router.py``) to attach a chosen
  :class:`TenantContext` for a valid bearer token, without touching Postgres;
* ``get_db`` is overridden with a minimal fake session that returns data
  configured per test;
* :class:`AuthorizationService` methods are monkeypatched so we can assert the
  router correctly delegates, shapes the response, and propagates domain errors
  to the standard envelope.

Covers (Req 7.2, 7.3, 7.4, 7.5, 5.1, 9.8):
- list roles returns fixed + custom roles
- create returns 201 + RoleWithActionsResponse
- clone returns 201 + role with action_ids
- patch returns updated role
- delete returns 204
- assign actions returns role + action_ids
- permissions tree returns nested structure
- RoleNameConflictError → 409 envelope
- unauthenticated → tenant_context_missing (403)
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

import app.api.routers.roles as router_mod
import app.middleware.auth_tenant as mw
from app.core.errors import (
    ActionModuleUnsubscribedError,
    NotAuthorizedError,
    RoleNameConflictError,
)
from app.core.security import create_access_token
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.main import create_app
from app.models.permission import Action, Module, Resource, SubModule
from app.models.role import Role, RolePermission


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class _NoopSession:
    """No-op async session context manager for the middleware context build."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):  # noqa: ANN001
        return _EmptyResult()


class _EmptyResult:
    def scalar_one_or_none(self):
        return None


def _noop_session_factory():
    return _NoopSession()


class _ScalarResult:
    """A fake scalars-chain result holding a pre-built list."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeDBSession:
    """Minimal fake session for request DB; returns data configured per test."""

    def __init__(self, execute_response: Any = None) -> None:
        # execute_response: callable(statement)->result, or None -> empty
        self._execute_response = execute_response

    async def execute(self, statement):  # noqa: ANN001
        if self._execute_response is not None:
            return self._execute_response(statement)
        return _ScalarResult([])

    async def get(self, model, pk):
        return None


def _role(
    *,
    is_custom: bool = True,
    role_type: str | None = None,
    customer_id: uuid.UUID | None = None,
    name: str | None = "Test Role",
) -> Role:
    r = Role(
        role_type=role_type,
        is_custom=is_custom,
        customer_id=customer_id,
        name=name,
    )
    r.id = uuid4()
    return r


def _fixed_role(role_type: str) -> Role:
    return _role(is_custom=False, role_type=role_type, customer_id=None, name=None)


def _customer_context(customer_id: uuid.UUID | None = None) -> TenantContext:
    cid = customer_id or uuid4()
    return TenantContext(
        user_id=uuid4(),
        role_type="customeradmin",
        agency_scope=None,
        customer_scope=frozenset({cid}),
        is_superadmin=False,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _token_for_ctx(ctx: TenantContext) -> str:
    return create_access_token(
        user_id=ctx.user_id, role_type=ctx.role_type, email="admin@example.com"
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixture: wired app with stubbed auth + configurable DB session
# ---------------------------------------------------------------------------


@pytest.fixture
def make_client(monkeypatch):
    """Factory that builds a TestClient with stubbed middleware.

    Usage::

        client, ctx, token = make_client(db_session=..., customer_id=...)

    ``db_session`` is the fake DB session injected via ``get_db``.
    ``customer_id`` optionally pins the customer scope.
    """

    def _build(
        db_session: _FakeDBSession | None = None,
        customer_id: uuid.UUID | None = None,
    ):
        ctx = _customer_context(customer_id)

        monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

        async def _fake_build(self, claims, impersonation=None, **kwargs):
            return ctx

        monkeypatch.setattr(mw.AuthorizationService, "build_tenant_context", _fake_build)

        _app = create_app()

        _session = db_session if db_session is not None else _FakeDBSession()

        async def _override_get_db():
            yield _session

        _app.dependency_overrides[get_db] = _override_get_db

        token = _token_for_ctx(ctx)
        client = TestClient(_app)
        return client, ctx, token

    return _build


# ---------------------------------------------------------------------------
# GET /roles
# ---------------------------------------------------------------------------


def test_list_roles_returns_fixed_and_custom_roles(make_client, monkeypatch):
    """List endpoint returns both fixed and custom roles (Req 7.3)."""
    customer_id = uuid4()
    superadmin = _fixed_role("superadmin")
    agencyadmin = _fixed_role("agencyadmin")
    customeradmin = _fixed_role("customeradmin")
    custom = _role(is_custom=True, customer_id=customer_id, name="Finance Manager")

    call_count = {"n": 0}

    def _execute(statement):
        call_count["n"] += 1
        # First call: fixed roles. Second call: custom roles.
        if call_count["n"] == 1:
            return _ScalarResult([superadmin, agencyadmin, customeradmin])
        return _ScalarResult([custom])

    db = _FakeDBSession(execute_response=_execute)
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.get(f"/roles?customer_id={customer_id}", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 4  # 3 fixed + 1 custom

    role_types = {r["role_type"] for r in body if r["role_type"] is not None}
    assert role_types == {"superadmin", "agencyadmin", "customeradmin"}
    custom_roles = [r for r in body if r["is_custom"]]
    assert len(custom_roles) == 1
    assert custom_roles[0]["name"] == "Finance Manager"
    assert custom_roles[0]["customer_id"] == str(customer_id)


# ---------------------------------------------------------------------------
# POST /roles
# ---------------------------------------------------------------------------


def test_create_role_returns_201_with_role_and_action_ids(make_client, monkeypatch):
    """Create endpoint returns 201 with the role and empty action_ids (Req 7.2)."""
    customer_id = uuid4()
    created = _role(is_custom=True, customer_id=customer_id, name="New Role")

    async def _fake_create(self, ctx, cid, name):
        assert str(cid) == str(customer_id)
        assert name == "New Role"
        return created

    monkeypatch.setattr(router_mod.AuthorizationService, "create_custom_role", _fake_create)

    # DB session returns empty action_ids for the role
    db = _FakeDBSession(execute_response=lambda _stmt: _ScalarResult([]))
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.post(
        "/roles",
        json={"customer_id": str(customer_id), "name": "New Role"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(created.id)
    assert body["is_custom"] is True
    assert body["name"] == "New Role"
    assert body["customer_id"] == str(customer_id)
    assert body["action_ids"] == []


def test_create_role_conflict_returns_409_envelope(make_client, monkeypatch):
    """RoleNameConflictError from service → 409 standard envelope (Req 7.2)."""
    customer_id = uuid4()

    async def _conflict(self, ctx, cid, name):
        raise RoleNameConflictError(details={"name": name})

    monkeypatch.setattr(router_mod.AuthorizationService, "create_custom_role", _conflict)

    db = _FakeDBSession()
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.post(
        "/roles",
        json={"customer_id": str(customer_id), "name": "Duplicate"},
        headers=_auth(token),
    )

    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "role_name_conflict"
    assert set(body["error"].keys()) == {"code", "message", "details"}


# ---------------------------------------------------------------------------
# POST /roles/{role_id}/clone
# ---------------------------------------------------------------------------


def test_clone_role_returns_201_with_action_ids(make_client, monkeypatch):
    """Clone endpoint returns 201 with the cloned role + copied action ids (Req 7.4)."""
    customer_id = uuid4()
    source_id = uuid4()
    action_id = uuid4()
    clone = _role(is_custom=True, customer_id=customer_id, name="Clone Name")

    async def _fake_clone(self, ctx, role_id, new_name):
        assert role_id == source_id
        assert new_name == "Clone Name"
        return clone

    monkeypatch.setattr(router_mod.AuthorizationService, "clone_custom_role", _fake_clone)

    # DB session returns one action_id for the clone
    db = _FakeDBSession(execute_response=lambda _stmt: _ScalarResult([action_id]))
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.post(
        f"/roles/{source_id}/clone",
        json={"new_name": "Clone Name"},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(clone.id)
    assert body["name"] == "Clone Name"
    assert body["action_ids"] == [str(action_id)]


# ---------------------------------------------------------------------------
# PATCH /roles/{role_id}
# ---------------------------------------------------------------------------


def test_patch_role_returns_updated_role(make_client, monkeypatch):
    """Patch endpoint renames the role and returns updated data (Req 7.3)."""
    customer_id = uuid4()
    role_id = uuid4()
    updated = _role(is_custom=True, customer_id=customer_id, name="Renamed Role")
    updated.id = role_id

    async def _fake_update(self, ctx, rid, *, name=None):
        assert rid == role_id
        assert name == "Renamed Role"
        return updated

    monkeypatch.setattr(router_mod.AuthorizationService, "update_custom_role", _fake_update)

    db = _FakeDBSession()
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.patch(
        f"/roles/{role_id}",
        json={"name": "Renamed Role"},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(role_id)
    assert body["name"] == "Renamed Role"
    assert body["is_custom"] is True


def test_patch_role_name_conflict_returns_409(make_client, monkeypatch):
    """PATCH propagates RoleNameConflictError as 409 envelope."""
    customer_id = uuid4()
    role_id = uuid4()

    async def _conflict(self, ctx, rid, *, name=None):
        raise RoleNameConflictError(details={"name": name})

    monkeypatch.setattr(router_mod.AuthorizationService, "update_custom_role", _conflict)

    db = _FakeDBSession()
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.patch(
        f"/roles/{role_id}",
        json={"name": "Conflicting"},
        headers=_auth(token),
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "role_name_conflict"


# ---------------------------------------------------------------------------
# DELETE /roles/{role_id}
# ---------------------------------------------------------------------------


def test_delete_role_returns_204(make_client, monkeypatch):
    """Delete endpoint returns 204 No Content (Req 7.3)."""
    customer_id = uuid4()
    role_id = uuid4()
    deleted = {"called": False}

    async def _fake_delete(self, ctx, rid):
        assert rid == role_id
        deleted["called"] = True

    monkeypatch.setattr(router_mod.AuthorizationService, "delete_custom_role", _fake_delete)

    db = _FakeDBSession()
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.delete(f"/roles/{role_id}", headers=_auth(token))

    assert resp.status_code == 204
    assert resp.content == b""
    assert deleted["called"] is True


def test_delete_role_not_authorized_returns_403(make_client, monkeypatch):
    """NotAuthorizedError on delete → 403 standard envelope."""
    customer_id = uuid4()
    role_id = uuid4()

    async def _forbidden(self, ctx, rid):
        raise NotAuthorizedError(details={"role_id": str(rid)})

    monkeypatch.setattr(router_mod.AuthorizationService, "delete_custom_role", _forbidden)

    db = _FakeDBSession()
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.delete(f"/roles/{role_id}", headers=_auth(token))

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_authorized"


# ---------------------------------------------------------------------------
# PUT /roles/{role_id}/actions
# ---------------------------------------------------------------------------


def test_assign_actions_returns_role_with_action_ids(make_client, monkeypatch):
    """Assign-actions endpoint returns 200 with role + updated action_ids (Req 7.5)."""
    customer_id = uuid4()
    role_id = uuid4()
    action_id_1 = uuid4()
    action_id_2 = uuid4()
    role = _role(is_custom=True, customer_id=customer_id, name="My Role")
    role.id = role_id

    async def _fake_assign(self, ctx, rid, action_ids):
        assert rid == role_id
        assert set(action_ids) == {action_id_1, action_id_2}
        return role

    monkeypatch.setattr(router_mod.AuthorizationService, "assign_actions", _fake_assign)

    # Return the two action_ids from DB
    db = _FakeDBSession(
        execute_response=lambda _stmt: _ScalarResult([action_id_1, action_id_2])
    )
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.put(
        f"/roles/{role_id}/actions",
        json={"action_ids": [str(action_id_1), str(action_id_2)]},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(role_id)
    assert set(body["action_ids"]) == {str(action_id_1), str(action_id_2)}


def test_assign_actions_unsubscribed_returns_403(make_client, monkeypatch):
    """ActionModuleUnsubscribedError → 403 standard envelope (Req 7.6)."""
    customer_id = uuid4()
    role_id = uuid4()
    action_id = uuid4()

    async def _unsubscribed(self, ctx, rid, action_ids):
        raise ActionModuleUnsubscribedError(details={"action_id": str(action_id)})

    monkeypatch.setattr(router_mod.AuthorizationService, "assign_actions", _unsubscribed)

    db = _FakeDBSession()
    client, ctx, token = make_client(db_session=db, customer_id=customer_id)

    resp = client.put(
        f"/roles/{role_id}/actions",
        json={"action_ids": [str(action_id)]},
        headers=_auth(token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "action_module_unsubscribed"


# ---------------------------------------------------------------------------
# GET /permissions/tree
# ---------------------------------------------------------------------------


def test_permissions_tree_returns_nested_structure(make_client, monkeypatch):
    """Permissions tree endpoint returns the nested module structure (Req 5.1)."""
    # Build a minimal tree: 1 module → 1 submodule → 1 resource → 2 actions.
    mod_id = uuid4()
    sm_id = uuid4()
    res_id = uuid4()
    act1_id = uuid4()
    act2_id = uuid4()

    mod = Module(key="billing", name="Billing")
    mod.id = mod_id

    sm = SubModule(key="invoices", name="Invoices", module_id=mod_id)
    sm.id = sm_id

    res = Resource(key="invoice", name="Invoice", submodule_id=sm_id)
    res.id = res_id

    act1 = Action(
        name="create",
        action_key="billing.invoices.invoice.create",
        is_sensitive=False,
        resource_id=res_id,
    )
    act1.id = act1_id

    act2 = Action(
        name="delete",
        action_key="billing.invoices.invoice.delete",
        is_sensitive=True,
        resource_id=res_id,
    )
    act2.id = act2_id

    call_count = {"n": 0}

    def _execute(statement):
        call_count["n"] += 1
        # execute is called 4 times in order: modules, submodules, resources, actions
        if call_count["n"] == 1:
            return _ScalarResult([mod])
        if call_count["n"] == 2:
            return _ScalarResult([sm])
        if call_count["n"] == 3:
            return _ScalarResult([res])
        return _ScalarResult([act1, act2])

    db = _FakeDBSession(execute_response=_execute)
    client, ctx, token = make_client(db_session=db)

    resp = client.get("/permissions/tree", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert "modules" in body
    assert len(body["modules"]) == 1

    module_node = body["modules"][0]
    assert module_node["module_id"] == str(mod_id)
    assert module_node["key"] == "billing"
    assert module_node["name"] == "Billing"
    assert len(module_node["submodules"]) == 1

    sm_node = module_node["submodules"][0]
    assert sm_node["submodule_id"] == str(sm_id)
    assert sm_node["key"] == "invoices"
    assert len(sm_node["resources"]) == 1

    res_node = sm_node["resources"][0]
    assert res_node["resource_id"] == str(res_id)
    assert res_node["key"] == "invoice"
    assert len(res_node["actions"]) == 2

    action_keys = {a["action_key"] for a in res_node["actions"]}
    assert action_keys == {
        "billing.invoices.invoice.create",
        "billing.invoices.invoice.delete",
    }
    sensitive_actions = [a for a in res_node["actions"] if a["is_sensitive"]]
    assert len(sensitive_actions) == 1
    assert sensitive_actions[0]["action_key"] == "billing.invoices.invoice.delete"


def test_permissions_tree_empty_db_returns_empty_modules(make_client):
    """When DB has no modules, tree returns empty modules list."""
    db = _FakeDBSession(execute_response=lambda _stmt: _ScalarResult([]))
    client, ctx, token = make_client(db_session=db)

    resp = client.get("/permissions/tree", headers=_auth(token))

    assert resp.status_code == 200
    assert resp.json() == {"modules": []}


# ---------------------------------------------------------------------------
# Unauthenticated
# ---------------------------------------------------------------------------


def test_unauthenticated_request_to_roles_is_rejected():
    """No bearer token → tenant_context_missing 403 (Req 9.8)."""
    _app = create_app()
    client = TestClient(_app)

    resp = client.get("/roles?customer_id=" + str(uuid4()))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"


def test_unauthenticated_request_to_permissions_tree_is_rejected():
    """No bearer token → tenant_context_missing 403 on permissions/tree (Req 9.8)."""
    _app = create_app()
    client = TestClient(_app)

    resp = client.get("/permissions/tree")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"

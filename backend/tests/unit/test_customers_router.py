"""Router tests for the customers & staff management endpoints.

Exercises ``/customers/*`` wired into the real FastAPI app through Starlette's
``TestClient``. Focus is on *wiring*: auth middleware is stubbed and DB session
is replaced with a lightweight fake, so tests do not touch Postgres or Redis.

Covers:
- ``GET /customers/me`` returns customer list for superadmin / agencyadmin /
  customeradmin.
- ``GET /customers/{id}/users`` returns staff list with roles.
- ``POST /customers/{id}/users`` creates a new user + CustomerUser + invite
  token (Redis stubbed).
- ``POST /customers/{id}/users`` with existing email already in customer → 409.
- ``DELETE /customers/{id}/users/{uid}`` returns 204.
- ``PUT /customers/{id}/users/{uid}/roles`` updates roles correctly.
- Unauthenticated request → 403 tenant_context_missing (Req 9.8).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

import app.api.routers.customers as router_mod
import app.middleware.auth_tenant as mw
from app.core.errors import NotAuthorizedError, UserAlreadyInCustomerError
from app.core.security import create_access_token
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.main import create_app
from app.models.customer import Customer
from app.models.customer_user import CustomerUser
from app.models.role import Role, UserRole
from app.models.user import User


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class _EmptyResult:
    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []


class _NoopSession:
    """Stub async session for the middleware's tenant context build."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):  # noqa: ANN001
        return _EmptyResult()


def _noop_session_factory():
    return _NoopSession()


class _ScalarResult:
    """Fake scalars-chain result wrapping a pre-built list."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDBSession:
    """Minimal async session stub — configurable per test."""

    def __init__(self) -> None:
        # List of results to return per execute() call (FIFO).
        self._execute_queue: list[Any] = []
        # Optional override: callable(stmt) → result, used when queue is empty.
        self._execute_fn = None
        # Rows added via session.add().
        self.added: list[Any] = []
        self.flushed = False
        self.committed = False
        # Object to return from session.get().
        self._get_result: Any = None

    def push_result(self, result: Any) -> None:
        """Queue a result for the next execute() call."""
        self._execute_queue.append(result)

    def set_execute_fn(self, fn) -> None:  # noqa: ANN001
        self._execute_fn = fn

    def set_get_result(self, obj: Any) -> None:
        self._get_result = obj

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, statement):  # noqa: ANN001
        if self._execute_queue:
            return self._execute_queue.pop(0)
        if self._execute_fn is not None:
            return self._execute_fn(statement)
        return _ScalarResult([])

    async def flush(self) -> None:
        self.flushed = True
        # Assign an id to any User without one (simulates DB sequence).
        for obj in self.added:
            if isinstance(obj, User) and obj.id is None:
                obj.id = uuid4()

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: Any) -> None:  # noqa: ANN001
        # No-op: the object is already fully populated in tests.
        pass

    async def get(self, model, pk):  # noqa: ANN001
        return self._get_result


# ---------------------------------------------------------------------------
# Model constructors
# ---------------------------------------------------------------------------


def _customer(*, agency_id: uuid.UUID | None = None) -> Customer:
    c = Customer(
        name="Acme Corp",
        status="active",
        agency_id=agency_id or uuid4(),
    )
    c.id = uuid4()
    return c


def _user(*, email: str = "alice@example.com", status: str = "active") -> User:
    u = User(
        email=email,
        role_type="customeradmin",
        status=status,
    )
    u.id = uuid4()
    return u


def _role_row(*, customer_id: uuid.UUID, name: str = "Finance Manager") -> Role:
    r = Role(
        is_custom=True,
        customer_id=customer_id,
        name=name,
    )
    r.id = uuid4()
    return r


# ---------------------------------------------------------------------------
# TenantContext factories
# ---------------------------------------------------------------------------


def _superadmin_ctx() -> TenantContext:
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


def _agencyadmin_ctx(agency_id: uuid.UUID) -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
        role_type="agencyadmin",
        agency_scope=agency_id,
        customer_scope=frozenset(),
        is_superadmin=False,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _customeradmin_ctx(customer_ids: list[uuid.UUID]) -> TenantContext:
    uid = uuid4()
    return TenantContext(
        user_id=uid,
        role_type="customeradmin",
        agency_scope=None,
        customer_scope=frozenset(customer_ids),
        is_superadmin=False,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _token_for_ctx(ctx: TenantContext) -> str:
    return create_access_token(
        user_id=ctx.user_id,
        role_type=ctx.role_type,
        email="admin@example.com",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixture: wired app with stubbed auth + configurable DB session + Redis
# ---------------------------------------------------------------------------


@pytest.fixture
def make_client(monkeypatch):
    """Factory that builds a TestClient with stubbed middleware.

    Usage::

        client, ctx, token = make_client(ctx=..., db=...)
    """

    def _build(ctx: TenantContext, db: _FakeDBSession | None = None):
        monkeypatch.setattr(mw, "AsyncSessionLocal", _noop_session_factory)

        async def _fake_build(self, claims, impersonation=None, **kwargs):
            return ctx

        monkeypatch.setattr(mw.AuthorizationService, "build_tenant_context", _fake_build)

        _app = create_app()
        _db = db if db is not None else _FakeDBSession()

        async def _override_get_db():
            yield _db

        _app.dependency_overrides[get_db] = _override_get_db

        token = _token_for_ctx(ctx)
        client = TestClient(_app)
        return client, ctx, token

    return _build


@pytest.fixture(autouse=True)
def stub_redis(monkeypatch):
    """Stub Redis so tests never hit a real server."""
    mock_redis = MagicMock()
    mock_redis.setex = AsyncMock(return_value=True)
    monkeypatch.setattr(router_mod, "get_redis", lambda: mock_redis)


# ---------------------------------------------------------------------------
# GET /customers/me — superadmin
# ---------------------------------------------------------------------------


def test_get_my_customers_superadmin_returns_all(make_client):
    """Superadmin receives all customers ordered by name."""
    ctx = _superadmin_ctx()
    c1 = _customer()
    c1.name = "Beta Corp"
    c2 = _customer()
    c2.name = "Alpha Inc"

    db = _FakeDBSession()
    db.push_result(_ScalarResult([c1, c2]))

    client, _, token = make_client(ctx, db)
    resp = client.get("/customers/me", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    names = [c["name"] for c in body]
    assert set(names) == {"Beta Corp", "Alpha Inc"}


# ---------------------------------------------------------------------------
# GET /customers/me — agencyadmin
# ---------------------------------------------------------------------------


def test_get_my_customers_agencyadmin_filters_by_agency(make_client):
    """Agencyadmin only sees customers in their agency."""
    agency_id = uuid4()
    ctx = _agencyadmin_ctx(agency_id)
    c = _customer(agency_id=agency_id)
    c.name = "Agency Customer"

    db = _FakeDBSession()
    db.push_result(_ScalarResult([c]))

    client, _, token = make_client(ctx, db)
    resp = client.get("/customers/me", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Agency Customer"
    assert body[0]["agency_id"] == str(agency_id)


# ---------------------------------------------------------------------------
# GET /customers/me — customeradmin
# ---------------------------------------------------------------------------


def test_get_my_customers_customeradmin_returns_assigned(make_client):
    """Customeradmin sees only their assigned customers."""
    cid = uuid4()
    ctx = _customeradmin_ctx([cid])
    c = _customer()
    c.id = cid
    c.name = "My Customer"

    db = _FakeDBSession()
    db.push_result(_ScalarResult([c]))

    client, _, token = make_client(ctx, db)
    resp = client.get("/customers/me", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == str(cid)


# ---------------------------------------------------------------------------
# GET /customers/{id}/users
# ---------------------------------------------------------------------------


def test_list_staff_returns_users_with_roles(make_client):
    """List-staff returns each user with their custom-role assignments."""
    cid = uuid4()
    ctx = _customeradmin_ctx([cid])
    u = _user(email="bob@example.com")
    role = _role_row(customer_id=cid, name="Viewer")

    db = _FakeDBSession()
    # First execute: users via customer_users join.
    db.push_result(_ScalarResult([u]))
    # Second execute: roles for the user (UserRole join Role).
    # Row tuple: (user_id, role_id, role_name).
    fake_row = MagicMock()
    fake_row.user_id = u.id
    fake_row.__getitem__ = lambda self, i: (u.id, role.id, role.name)[i]
    db.push_result(_ScalarResult([fake_row]))

    client, _, token = make_client(ctx, db)
    resp = client.get(f"/customers/{cid}/users", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    staff = body[0]
    assert staff["email"] == "bob@example.com"
    assert staff["name"] == "bob"
    assert len(staff["roles"]) == 1
    assert staff["roles"][0]["role_name"] == "Viewer"


def test_list_staff_outside_scope_returns_403(make_client):
    """Customer outside the caller's scope is rejected."""
    cid = uuid4()
    other_cid = uuid4()
    ctx = _customeradmin_ctx([cid])  # does NOT include other_cid

    db = _FakeDBSession()
    client, _, token = make_client(ctx, db)
    resp = client.get(f"/customers/{other_cid}/users", headers=_auth(token))

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_authorized"


# ---------------------------------------------------------------------------
# POST /customers/{id}/users — new user
# ---------------------------------------------------------------------------


def test_invite_staff_creates_new_user_and_returns_201(make_client, monkeypatch):
    """Inviting a new email creates a User, CustomerUser, stores invite token."""
    cid = uuid4()
    ctx = _customeradmin_ctx([cid])

    db = _FakeDBSession()
    # execute 1: user lookup by email → not found.
    db.push_result(_ScalarResult([]))
    # execute 2: _validate_custom_roles (no role_ids in this test, skip)
    # execute 3: _load_roles_for_users → empty roles.
    db.push_result(_ScalarResult([]))

    client, _, token = make_client(ctx, db)
    resp = client.post(
        f"/customers/{cid}/users",
        json={"email": "newstaff@example.com", "name": "New Staff", "role_ids": []},
        headers=_auth(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "newstaff@example.com"
    assert body["name"] == "newstaff"

    # A User and CustomerUser should have been added to the session.
    added_types = [type(o).__name__ for o in db.added]
    assert "User" in added_types
    assert "CustomerUser" in added_types


def test_invite_staff_existing_email_already_in_customer_returns_409(make_client):
    """Inviting an email already in the customer → 409 user_already_in_customer."""
    cid = uuid4()
    ctx = _customeradmin_ctx([cid])
    existing_user = _user(email="already@example.com")
    existing_cu = CustomerUser(user_id=existing_user.id, customer_id=cid)
    existing_cu.id = uuid4()

    db = _FakeDBSession()
    # execute 1: user lookup by email → found.
    db.push_result(_ScalarResult([existing_user]))
    # execute 2: CustomerUser lookup → found (already in customer).
    db.push_result(_ScalarResult([existing_cu]))

    client, _, token = make_client(ctx, db)
    resp = client.post(
        f"/customers/{cid}/users",
        json={"email": "already@example.com", "name": "Test", "role_ids": []},
        headers=_auth(token),
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "user_already_in_customer"


# ---------------------------------------------------------------------------
# DELETE /customers/{id}/users/{uid}
# ---------------------------------------------------------------------------


def test_remove_staff_returns_204(make_client):
    """Remove-staff deletes CustomerUser + UserRole rows and returns 204."""
    cid = uuid4()
    uid = uuid4()
    ctx = _customeradmin_ctx([cid])

    db = _FakeDBSession()
    # execute 1: delete(UserRole) — returns a fake result.
    db.push_result(_ScalarResult([]))
    # execute 2: delete(CustomerUser).
    db.push_result(_ScalarResult([]))

    client, _, token = make_client(ctx, db)
    resp = client.delete(f"/customers/{cid}/users/{uid}", headers=_auth(token))

    assert resp.status_code == 204
    assert resp.content == b""
    assert db.committed


def test_remove_staff_outside_scope_returns_403(make_client):
    """Removing staff from an inaccessible customer → 403."""
    cid = uuid4()
    other_cid = uuid4()
    uid = uuid4()
    ctx = _customeradmin_ctx([cid])

    db = _FakeDBSession()
    client, _, token = make_client(ctx, db)
    resp = client.delete(f"/customers/{other_cid}/users/{uid}", headers=_auth(token))

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_authorized"


# ---------------------------------------------------------------------------
# PUT /customers/{id}/users/{uid}/roles
# ---------------------------------------------------------------------------


def test_update_staff_roles_replaces_roles(make_client):
    """Updating roles deletes old UserRole rows and inserts new ones."""
    cid = uuid4()
    uid = uuid4()
    role_id = uuid4()
    ctx = _customeradmin_ctx([cid])

    user = _user()
    user.id = uid
    role = _role_row(customer_id=cid)
    role.id = role_id

    db = _FakeDBSession()
    # execute 1: _validate_custom_roles → role found.
    db.push_result(_ScalarResult([role_id]))
    # execute 2: delete(UserRole).
    db.push_result(_ScalarResult([]))
    # execute 3: _load_roles_for_users join.
    fake_row = MagicMock()
    fake_row.user_id = uid
    fake_row.__getitem__ = lambda self, i: (uid, role.id, role.name)[i]
    db.push_result(_ScalarResult([fake_row]))
    # session.get(User) → return user.
    db.set_get_result(user)

    client, _, token = make_client(ctx, db)
    resp = client.put(
        f"/customers/{cid}/users/{uid}/roles",
        json={"role_ids": [str(role_id)]},
        headers=_auth(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(uid)
    assert len(body["roles"]) == 1
    assert body["roles"][0]["role_id"] == str(role_id)

    # A new UserRole should have been added.
    added_user_roles = [o for o in db.added if isinstance(o, UserRole)]
    assert len(added_user_roles) == 1
    assert added_user_roles[0].role_id == role_id


def test_update_staff_roles_invalid_role_id_returns_403(make_client):
    """PUT /roles with a role_id outside the customer raises 403."""
    cid = uuid4()
    uid = uuid4()
    ctx = _customeradmin_ctx([cid])
    invalid_role_id = uuid4()

    db = _FakeDBSession()
    # _validate_custom_roles: returns empty → role not found.
    db.push_result(_ScalarResult([]))

    client, _, token = make_client(ctx, db)
    resp = client.put(
        f"/customers/{cid}/users/{uid}/roles",
        json={"role_ids": [str(invalid_role_id)]},
        headers=_auth(token),
    )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_authorized"


# ---------------------------------------------------------------------------
# Unauthenticated
# ---------------------------------------------------------------------------


def test_unauthenticated_request_returns_403():
    """No bearer token → tenant_context_missing 403 (Req 9.8)."""
    _app = create_app()
    client = TestClient(_app)

    resp = client.get("/customers/me")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_context_missing"

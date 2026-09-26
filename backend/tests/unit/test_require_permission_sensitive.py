"""Unit tests for the sensitive-action gate in ``require_permission`` (Task 18.2).

These tests target Requirement 13 directly:

* **13.2** — WHILE impersonating, a sensitive Action is rejected with
  ``action_restricted_during_impersonation`` (403) and the guarded handler is
  never entered (no mutation).
* **13.3** — WHILE impersonating, a non-sensitive Action still passes through
  the *same* permission (and module) checks that apply outside impersonation:
  a caller with the grant is allowed; a caller without it gets ``not_authorized``.
* **13.4** — Because ``_load_action`` reads the Action (and its ``is_sensitive``
  flag) from the DB on every request with no caching, changing the flag between
  two requests flips the outcome.

The tests wire a tiny FastAPI app with a single route guarded by
``require_permission(action_key)`` and attach a chosen ``TenantContext`` to
``request.state`` via a probe middleware, mirroring how
``tests/unit/test_auth_tenant_middleware.py`` builds probe routes. The DB is not
touched: ``deps._load_action`` and ``AuthorizationService.has_permission`` /
``is_module_usable`` are stubbed, matching the fakes used across the
``test_authorization_service_*`` suite. A per-request handler side-effect flag
lets us assert the handler did (or did not) run.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

import app.api.deps as deps
from app.api.deps import require_permission
from app.core.errors import register_exception_handlers
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.permission import Action
from app.services.authorization_service import AuthorizationService

ACTION_KEY = "inventory.items.things.update"


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


def _make_action(*, is_sensitive: bool) -> Action:
    """A bare :class:`Action` instance with the fields the gate reads.

    Constructed without touching the DB; ``_module_id`` is stashed the same way
    :func:`deps._load_action` does so the (stubbed) module gate has a value.
    """
    action = Action(
        resource_id=uuid.uuid4(),
        name="update",
        is_sensitive=is_sensitive,
        action_key=ACTION_KEY,
    )
    action.__dict__["_module_id"] = uuid.uuid4()
    return action


def _context(
    *,
    impersonating: bool,
    is_superadmin: bool = False,
    role_type: str = "customeradmin",
) -> TenantContext:
    customer = uuid.uuid4()
    impersonator = uuid.uuid4() if impersonating else None
    return TenantContext(
        user_id=impersonator or uuid.uuid4(),
        role_type=role_type,
        agency_scope=None,
        customer_scope=frozenset({customer}),
        is_superadmin=is_superadmin,
        impersonating=impersonating,
        impersonated_agency_id=None,
        impersonated_customer_id=customer if impersonating else None,
        impersonator_user_id=impersonator,
        custom_role_customer_id=None,
    )


class _NoopSession:
    """A stand-in AsyncSession; never actually queried because the DB-facing
    helpers are stubbed. Provided so ``get_db`` yields *something*."""


def _build_app(ctx: TenantContext) -> tuple[FastAPI, dict]:
    """Build a minimal app with one guarded route and a side-effect recorder.

    Returns the app plus a mutable ``state`` dict whose ``handler_ran`` flag the
    guarded handler flips *only if it executes* — the marker used to assert
    "perform no mutation" (Req 13.2).
    """
    app = FastAPI()
    register_exception_handlers(app)
    state = {"handler_ran": False}

    @app.middleware("http")
    async def _attach_context(request: Request, call_next):
        request.state.tenant_context = ctx
        return await call_next(request)

    @app.post("/_probe/guarded")
    async def _guarded(
        _ctx: TenantContext = Depends(require_permission(ACTION_KEY)),
    ):
        state["handler_ran"] = True
        return {"ok": True}

    async def _fake_get_db():
        yield _NoopSession()

    app.dependency_overrides[get_db] = _fake_get_db
    return app, state


@pytest.fixture(autouse=True)
def _stub_module_gate(monkeypatch):
    """Default the module gate to "usable" so it never masks the behavior under
    test. Individual tests can override permission separately."""

    async def _usable(self, customer_id, module_id):  # noqa: ANN001
        return True

    monkeypatch.setattr(AuthorizationService, "is_module_usable", _usable)


def _stub_permission(monkeypatch, *, allowed: bool) -> None:
    async def _has_permission(self, ctx, action_key):  # noqa: ANN001
        return allowed

    monkeypatch.setattr(AuthorizationService, "has_permission", _has_permission)


def _stub_action(monkeypatch, *, is_sensitive: bool) -> None:
    async def _load(db, action_key):  # noqa: ANN001
        return _make_action(is_sensitive=is_sensitive)

    monkeypatch.setattr(deps, "_load_action", _load)


# ---------------------------------------------------------------------------
# 13.2 — sensitive action during impersonation is rejected, handler not run
# ---------------------------------------------------------------------------


def test_impersonating_sensitive_action_is_rejected_and_handler_not_run(
    monkeypatch,
):
    _stub_permission(monkeypatch, allowed=True)  # has the grant, but…
    _stub_action(monkeypatch, is_sensitive=True)
    app, state = _build_app(_context(impersonating=True))

    resp = TestClient(app).post("/_probe/guarded")

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "action_restricted_during_impersonation"
    # Req 13.2: no mutation — the guarded handler must not have executed.
    assert state["handler_ran"] is False


# ---------------------------------------------------------------------------
# 13.3 — non-sensitive action during impersonation applies the SAME checks
# ---------------------------------------------------------------------------


def test_impersonating_non_sensitive_with_permission_is_allowed(monkeypatch):
    _stub_permission(monkeypatch, allowed=True)
    _stub_action(monkeypatch, is_sensitive=False)
    app, state = _build_app(_context(impersonating=True))

    resp = TestClient(app).post("/_probe/guarded")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert state["handler_ran"] is True


def test_impersonating_non_sensitive_without_permission_is_not_authorized(
    monkeypatch,
):
    # Req 13.3: the sensitive gate must NOT bypass the normal permission check;
    # a non-sensitive action still needs a valid grant during impersonation.
    _stub_permission(monkeypatch, allowed=False)
    _stub_action(monkeypatch, is_sensitive=False)
    app, state = _build_app(_context(impersonating=True))

    resp = TestClient(app).post("/_probe/guarded")

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "not_authorized"
    assert state["handler_ran"] is False


# ---------------------------------------------------------------------------
# Sensitive actions are fine when NOT impersonating
# ---------------------------------------------------------------------------


def test_not_impersonating_sensitive_action_with_permission_is_allowed(
    monkeypatch,
):
    _stub_permission(monkeypatch, allowed=True)
    _stub_action(monkeypatch, is_sensitive=True)
    app, state = _build_app(_context(impersonating=False))

    resp = TestClient(app).post("/_probe/guarded")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert state["handler_ran"] is True


# ---------------------------------------------------------------------------
# Superadmin impersonating a tenant is still blocked on a sensitive action
# ---------------------------------------------------------------------------


def test_superadmin_impersonating_sensitive_action_is_still_blocked(monkeypatch):
    # Per Task 18.1 an impersonated context drops to the impersonated boundary
    # (is_superadmin=False, impersonating=True). Even if the underlying grant
    # would pass, the sensitive gate applies.
    _stub_permission(monkeypatch, allowed=True)
    _stub_action(monkeypatch, is_sensitive=True)
    # is_superadmin stays False while impersonating (18.1 boundary drop).
    app, state = _build_app(
        _context(impersonating=True, is_superadmin=False, role_type="superadmin")
    )

    resp = TestClient(app).post("/_probe/guarded")

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "action_restricted_during_impersonation"
    assert state["handler_ran"] is False


# ---------------------------------------------------------------------------
# 13.4 — a change to is_sensitive applies to subsequent requests
# ---------------------------------------------------------------------------


def test_flag_change_applies_to_subsequent_requests(monkeypatch):
    # The Action (and its is_sensitive) is read from the DB per request with no
    # caching, so flipping the flag between two invocations flips the outcome.
    _stub_permission(monkeypatch, allowed=True)

    flag = {"is_sensitive": False}

    async def _load(db, action_key):  # noqa: ANN001
        return _make_action(is_sensitive=flag["is_sensitive"])

    monkeypatch.setattr(deps, "_load_action", _load)

    app, state = _build_app(_context(impersonating=True))
    client = TestClient(app)

    # First request: flag false → allowed.
    resp1 = client.post("/_probe/guarded")
    assert resp1.status_code == 200
    assert state["handler_ran"] is True

    # Flip the flag as a subsequent DB state would, reset the marker, re-issue.
    flag["is_sensitive"] = True
    state["handler_ran"] = False
    resp2 = client.post("/_probe/guarded")
    assert resp2.status_code == 403
    assert resp2.json()["error"]["code"] == "action_restricted_during_impersonation"
    assert state["handler_ran"] is False

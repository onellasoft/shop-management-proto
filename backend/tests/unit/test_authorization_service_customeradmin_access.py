"""Unit tests for Req 7.3 — customeradmin operations within an accessed customer.

Requirement 7.3: *WHERE a Customeradmin holds access to a Customer, THE
Authorization_Service SHALL permit the Customeradmin to use, modify, delete,
create, or clone Custom_Roles within that Customer.*

This module asserts the **positive** direction of Req 7.3 end-to-end for a
single customeradmin context whose ``customer_scope`` includes a customer ``C``:
every one of create / clone / update (modify) / delete / assign-actions (use)
succeeds against a role that lives within ``C``. Scope-rejection cases (roles
outside the accessed customer, ambiguous scope) are covered separately in
``test_authorization_service_custom_roles.py``; here the focus is that access to
the customer is sufficient to perform the full set of operations.

The database boundary reuses the in-memory fake ``AsyncSession`` and the
``_ctx`` / ``_custom_role`` helpers from
``test_authorization_service_custom_roles`` so the service's real filtering and
scope-resolution logic is exercised without a live Postgres database.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.role import RolePermission
from app.services.authorization_service import AuthorizationService

from .test_authorization_service_custom_roles import (
    _FakeSession,
    _ctx,
    _custom_role,
)


def _service(session) -> AuthorizationService:
    return AuthorizationService(session)


# ---------------------------------------------------------------------------
# Req 7.3 — every operation is permitted within an accessed customer
# ---------------------------------------------------------------------------


async def test_customeradmin_can_create_role_within_accessed_customer():
    customer = uuid4()
    ctx = _ctx(customer)  # customer_scope includes the accessed customer
    session = _FakeSession()
    svc = _service(session)

    role = await svc.create_custom_role(ctx, customer, "Finance")

    assert role.is_custom is True
    assert role.customer_id == customer
    assert role in session.roles


async def test_customeradmin_can_clone_role_within_accessed_customer():
    customer = uuid4()
    ctx = _ctx(customer)
    source = _custom_role(customer, "Finance")
    a1, a2 = uuid4(), uuid4()
    perms = [
        RolePermission(role_id=source.id, action_id=a1),
        RolePermission(role_id=source.id, action_id=a2),
    ]
    session = _FakeSession(roles=[source], permissions=perms)
    svc = _service(session)

    clone = await svc.clone_custom_role(ctx, source.id, "Finance Copy")

    assert clone.id != source.id
    assert clone.customer_id == customer
    assert clone.name == "Finance Copy"
    cloned_actions = {
        p.action_id for p in session.permissions if p.role_id == clone.id
    }
    assert cloned_actions == {a1, a2}


async def test_customeradmin_can_modify_role_within_accessed_customer():
    customer = uuid4()
    ctx = _ctx(customer)
    role = _custom_role(customer, "Old")
    session = _FakeSession(roles=[role])
    svc = _service(session)

    updated = await svc.update_custom_role(ctx, role.id, name="New")

    assert updated.name == "New"


async def test_customeradmin_can_delete_role_within_accessed_customer():
    customer = uuid4()
    ctx = _ctx(customer)
    role = _custom_role(customer, "Finance")
    perms = [
        RolePermission(role_id=role.id, action_id=uuid4()),
        RolePermission(role_id=role.id, action_id=uuid4()),
    ]
    session = _FakeSession(roles=[role], permissions=perms)
    svc = _service(session)

    await svc.delete_custom_role(ctx, role.id)

    assert role not in session.roles
    assert [p for p in session.permissions if p.role_id == role.id] == []


async def test_customeradmin_can_use_role_via_action_assignment_within_accessed_customer():
    # "use" a role within the accessed customer by reconciling its Action set.
    # Clearing to the empty set is subscription-independent (no Module gate is
    # triggered when no Actions are requested), so it demonstrates that the
    # assign operation is permitted within the accessed customer's scope.
    customer = uuid4()
    ctx = _ctx(customer)
    role = _custom_role(customer, "Finance")
    perms = [RolePermission(role_id=role.id, action_id=uuid4())]
    session = _FakeSession(roles=[role], permissions=perms)
    svc = _service(session)

    result = await svc.assign_actions(ctx, role.id, [])

    assert result is role
    assert [p for p in session.permissions if p.role_id == role.id] == []


async def test_customeradmin_full_lifecycle_within_accessed_customer():
    # End-to-end: create → clone → modify → assign → delete all succeed for a
    # customeradmin whose scope includes the accessed customer (Req 7.3).
    customer = uuid4()
    ctx = _ctx(customer)
    session = _FakeSession()
    svc = _service(session)

    created = await svc.create_custom_role(ctx, customer, "Base")
    cloned = await svc.clone_custom_role(ctx, created.id, "Base Copy")
    modified = await svc.update_custom_role(ctx, cloned.id, name="Renamed")
    used = await svc.assign_actions(ctx, modified.id, [])
    await svc.delete_custom_role(ctx, used.id)

    assert created in session.roles
    assert modified.name == "Renamed"
    assert modified.customer_id == customer
    assert used is modified
    assert modified not in session.roles

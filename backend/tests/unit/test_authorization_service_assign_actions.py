"""Unit tests for AuthorizationService.assign_actions (Task 11.2).

Requirement 7.5: WHEN a Customeradmin assigns Actions to a Custom_Role, THE
Authorization_Service SHALL permit only Actions belonging to Modules that are
present in the Customer's Module_Subscriptions at the time of assignment.

Requirement 7.6 / 7.9: IF a Customeradmin attempts to assign/edit an Action
belonging to a Module not present in the Customer's Module_Subscriptions, THEN
THE Authorization_Service SHALL reject the assignment, leave the Custom_Role's
existing Actions unchanged, and return an authorization error.

Requirement 7.7 / 7.8 / 8.6: a Module re-added to the subscriptions permits its
Actions to be assigned again; removed/expired Modules keep their existing
role_permissions rows (retention is achieved by leaving the definition
untouched on rejection, evaluated as non-usable at enforcement time).

These are pure-logic tests. The database boundary is an in-memory fake
``AsyncSession`` that interprets the specific query shapes ``assign_actions``
issues:

* ``select(Role).where(...)``                        → role lookup
* ``select(Action.id, SubModule.module_id).join(...)`` → module resolution
* ``select(...).where(CustomerSubscription...)``     → is_module_usable read
* ``select(RolePermission).where(...)``              → existing grants
"""

from __future__ import annotations

import datetime
from uuid import uuid4

import pytest

from app.core.errors import ActionModuleUnsubscribedError, NotAuthorizedError
from app.core.tenant_context import TenantContext
from app.models.permission import Action, Resource, SubModule
from app.models.role import Role, RolePermission
from app.models.subscription import CustomerSubscription
from app.services.authorization_service import AuthorizationService

pytestmark = pytest.mark.asyncio

NOW = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# In-memory permission graph + subscription world
# ---------------------------------------------------------------------------


class _World:
    """Holds the ORM rows the fake session queries against.

    Actions map to a module via ``action_id -> module_id`` (the fake collapses
    the resources/submodules chain). ``subscriptions`` maps
    ``(customer_id, module_id) -> (status, expires_at)``.
    """

    def __init__(self) -> None:
        self.roles: list[Role] = []
        self.permissions: list[RolePermission] = []
        self.action_module: dict = {}
        self.subscriptions: dict = {}

    def add_role(self, role: Role) -> None:
        self.roles.append(role)

    def add_action(self, action_id, module_id) -> None:
        self.action_module[action_id] = module_id

    def subscribe(self, customer_id, module_id, status="active", expires_at=None):
        self.subscriptions[(customer_id, module_id)] = (status, expires_at)

    def unsubscribe(self, customer_id, module_id) -> None:
        self.subscriptions.pop((customer_id, module_id), None)


class _Result:
    def __init__(self, tuple_rows, scalar_rows=None):
        self._tuple_rows = tuple_rows
        self._scalar_rows = scalar_rows if scalar_rows is not None else tuple_rows

    def all(self):
        return list(self._tuple_rows)

    def first(self):
        return self._tuple_rows[0] if self._tuple_rows else None

    def scalars(self):
        return _ScalarResult(self._scalar_rows)

    def scalar_one_or_none(self):
        if not self._scalar_rows:
            return None
        if len(self._scalar_rows) > 1:
            raise AssertionError("scalar_one_or_none matched multiple rows")
        return self._scalar_rows[0]


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    """AsyncSession stand-in backed by an in-memory ``_World``."""

    def __init__(self, world: _World) -> None:
        self.world = world
        self._pending: list = []
        self.rolled_back = False

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        self._pending.append(obj)

    async def delete(self, obj) -> None:
        if isinstance(obj, RolePermission) and obj in self.world.permissions:
            self.world.permissions.remove(obj)
        elif isinstance(obj, Role) and obj in self.world.roles:
            self.world.roles.remove(obj)

    async def flush(self) -> None:
        for obj in self._pending:
            if isinstance(obj, RolePermission):
                self.world.permissions.append(obj)
            elif isinstance(obj, Role):
                self.world.roles.append(obj)
        self._pending = []

    async def rollback(self) -> None:
        self.rolled_back = True
        self._pending = []

    async def execute(self, statement):  # noqa: ANN001
        descs = statement.column_descriptions
        entities = {d["entity"] for d in descs}
        exprs = [d["expr"] for d in descs]

        # is_module_usable: select(status, expires_at) from CustomerSubscription
        if CustomerSubscription in entities:
            cust_id, mod_id = self._extract_subscription_filters(statement)
            row = self.world.subscriptions.get((cust_id, mod_id))
            return _Result([row] if row is not None else [])

        # module resolution: select(Action.id, SubModule.module_id).join(...)
        if Action in entities and SubModule in entities:
            wanted = self._extract_in_values(statement)
            rows = [
                (aid, self.world.action_module[aid])
                for aid in wanted
                if aid in self.world.action_module
            ]
            return _Result(rows)

        # role lookup: select(Role).where(...)
        if descs[0]["entity"] is Role:
            role_id, customer_id = self._extract_role_filters(statement)
            matches = [
                r
                for r in self.world.roles
                if r.id == role_id
                and r.is_custom is True
                and r.customer_id == customer_id
            ]
            return _Result(matches, scalar_rows=matches)

        # existing grants: select(RolePermission).where(role_id == ...)
        if descs[0]["entity"] is RolePermission:
            role_id = self._extract_role_permission_role_id(statement)
            matches = [
                p for p in self.world.permissions if p.role_id == role_id
            ]
            return _Result(matches, scalar_rows=matches)

        raise AssertionError(f"unexpected statement entities: {entities}")

    # -- crude WHERE-clause extraction helpers -----------------------------

    @staticmethod
    def _iter_binary(clause):
        from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

        if clause is None:
            return
        if isinstance(clause, BooleanClauseList):
            for c in clause.clauses:
                yield from _FakeSession._iter_binary(c)
        elif isinstance(clause, BinaryExpression):
            yield clause

    def _extract_role_filters(self, statement):
        role_id = None
        customer_id = None
        for b in self._iter_binary(statement.whereclause):
            key = getattr(b.left, "key", None)
            val = getattr(b.right, "value", None)
            if key == "id":
                role_id = val
            elif key == "customer_id":
                customer_id = val
        return role_id, customer_id

    def _extract_role_permission_role_id(self, statement):
        for b in self._iter_binary(statement.whereclause):
            if getattr(b.left, "key", None) == "role_id":
                return getattr(b.right, "value", None)
        return None

    def _extract_subscription_filters(self, statement):
        cust_id = None
        mod_id = None
        for b in self._iter_binary(statement.whereclause):
            key = getattr(b.left, "key", None)
            val = getattr(b.right, "value", None)
            if key == "customer_id":
                cust_id = val
            elif key == "module_id":
                mod_id = val
        return cust_id, mod_id

    def _extract_in_values(self, statement):
        for b in self._iter_binary(statement.whereclause):
            right = b.right
            # IN clause: right is a BindParameter with an expanding value list
            val = getattr(right, "value", None)
            if isinstance(val, (list, tuple)):
                return list(val)
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service(world: _World) -> AuthorizationService:
    return AuthorizationService(_FakeSession(world), now=lambda: NOW)


def _ctx(customer_id) -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
        role_type="customeradmin",
        agency_scope=None,
        customer_scope=frozenset({customer_id}),
        is_superadmin=False,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _custom_role(customer_id, name="Finance") -> Role:
    r = Role(role_type=None, is_custom=True, customer_id=customer_id, name=name)
    r.id = uuid4()
    return r


def _grants_for(world: _World, role_id):
    return {p.action_id for p in world.permissions if p.role_id == role_id}


# ===========================================================================
# Happy path — assigning actions from subscribed modules (Req 7.5)
# ===========================================================================


async def test_assigns_actions_from_subscribed_modules():
    customer = uuid4()
    module = uuid4()
    a1, a2 = uuid4(), uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    world.add_action(a1, module)
    world.add_action(a2, module)
    world.subscribe(customer, module)

    svc = _service(world)
    result = await svc.assign_actions(_ctx(customer), role.id, [a1, a2])

    assert result is role
    assert _grants_for(world, role.id) == {a1, a2}


async def test_assign_deduplicates_action_ids():
    customer = uuid4()
    module = uuid4()
    a1 = uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    world.add_action(a1, module)
    world.subscribe(customer, module)

    svc = _service(world)
    await svc.assign_actions(_ctx(customer), role.id, [a1, a1, a1])

    grants = [p for p in world.permissions if p.role_id == role.id]
    assert len(grants) == 1


async def test_assign_replaces_existing_grants():
    customer = uuid4()
    module = uuid4()
    a1, a2, a3 = uuid4(), uuid4(), uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    for a in (a1, a2, a3):
        world.add_action(a, module)
    world.subscribe(customer, module)
    # Pre-existing grants: a1, a2
    world.permissions.append(RolePermission(role_id=role.id, action_id=a1))
    world.permissions.append(RolePermission(role_id=role.id, action_id=a2))

    svc = _service(world)
    await svc.assign_actions(_ctx(customer), role.id, [a2, a3])

    # a1 removed, a2 kept, a3 added.
    assert _grants_for(world, role.id) == {a2, a3}


async def test_assign_empty_clears_grants():
    customer = uuid4()
    module = uuid4()
    a1 = uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    world.add_action(a1, module)
    world.subscribe(customer, module)
    world.permissions.append(RolePermission(role_id=role.id, action_id=a1))

    svc = _service(world)
    await svc.assign_actions(_ctx(customer), role.id, [])

    assert _grants_for(world, role.id) == set()


# ===========================================================================
# Rejection — unsubscribed module leaves existing actions unchanged (7.6/7.9)
# ===========================================================================


async def test_rejects_action_from_unsubscribed_module():
    customer = uuid4()
    subscribed = uuid4()
    unsubscribed = uuid4()
    ok, bad = uuid4(), uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    world.add_action(ok, subscribed)
    world.add_action(bad, unsubscribed)
    world.subscribe(customer, subscribed)
    # unsubscribed module has no subscription row

    svc = _service(world)
    with pytest.raises(ActionModuleUnsubscribedError):
        await svc.assign_actions(_ctx(customer), role.id, [ok, bad])


async def test_rejection_leaves_existing_actions_unchanged():
    customer = uuid4()
    subscribed = uuid4()
    unsubscribed = uuid4()
    existing_a = uuid4()
    ok, bad = uuid4(), uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    world.add_action(existing_a, subscribed)
    world.add_action(ok, subscribed)
    world.add_action(bad, unsubscribed)
    world.subscribe(customer, subscribed)
    # Pre-existing grant that must survive the failed assignment.
    world.permissions.append(
        RolePermission(role_id=role.id, action_id=existing_a)
    )

    svc = _service(world)
    with pytest.raises(ActionModuleUnsubscribedError):
        await svc.assign_actions(_ctx(customer), role.id, [ok, bad])

    # Req 7.6 — existing actions unchanged; no partial application of `ok`.
    assert _grants_for(world, role.id) == {existing_a}


async def test_rejects_expired_module_action():
    customer = uuid4()
    module = uuid4()
    a1 = uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    world.add_action(a1, module)
    # Active but expired subscription -> non-usable.
    world.subscribe(
        customer, module, expires_at=NOW - datetime.timedelta(seconds=1)
    )

    svc = _service(world)
    with pytest.raises(ActionModuleUnsubscribedError):
        await svc.assign_actions(_ctx(customer), role.id, [a1])


async def test_rejects_unknown_action_id():
    customer = uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)

    svc = _service(world)
    with pytest.raises(ActionModuleUnsubscribedError):
        await svc.assign_actions(_ctx(customer), role.id, [uuid4()])


# ===========================================================================
# Re-add restores assignability (Req 7.7, 7.8, 8.6)
# ===========================================================================


async def test_readding_module_allows_assignment_again():
    customer = uuid4()
    module = uuid4()
    a1 = uuid4()
    world = _World()
    role = _custom_role(customer)
    world.add_role(role)
    world.add_action(a1, module)

    svc = _service(world)

    # Initially unsubscribed -> rejected.
    with pytest.raises(ActionModuleUnsubscribedError):
        await svc.assign_actions(_ctx(customer), role.id, [a1])

    # Re-add the module -> assignment now succeeds (Req 7.7).
    world.subscribe(customer, module)
    await svc.assign_actions(_ctx(customer), role.id, [a1])
    assert _grants_for(world, role.id) == {a1}


# ===========================================================================
# Scope enforcement (Req 7.3)
# ===========================================================================


async def test_rejects_role_outside_customer_scope():
    customer = uuid4()
    other = uuid4()
    role = _custom_role(other)
    world = _World()
    world.add_role(role)

    svc = _service(world)
    with pytest.raises(NotAuthorizedError):
        await svc.assign_actions(_ctx(customer), role.id, [])


async def test_rejects_unknown_role():
    customer = uuid4()
    world = _World()
    svc = _service(world)
    with pytest.raises(NotAuthorizedError):
        await svc.assign_actions(_ctx(customer), uuid4(), [])

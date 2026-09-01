"""Property-based tests for custom-role scoping, cloning, subscription-gated
action assignment, and subscription add/remove round-trips (Task 11.5).

# Feature: onella-backend, Property 12: Custom role name scoping and uniqueness
# Feature: onella-backend, Property 13: Custom role clone preserves action set
# Feature: onella-backend, Property 14: Action assignment limited to subscribed modules
# Feature: onella-backend, Property 16: Subscription add/remove round-trip preserves definitions

Property 12 — **Validates: Requirements 7.2**
    For any Customer, a custom-role name is accepted only when it is unique
    within that Customer and its trimmed length is 1–100 characters; the role is
    scoped to that single Customer; and the same name is allowed across
    different Customers.

Property 13 — **Validates: Requirements 7.4**
    For any source custom role, cloning produces a new role whose assigned
    Action set is identical to the source's, with a name unique within the
    Customer.

Property 14 — **Validates: Requirements 7.5, 7.6, 7.7, 7.9**
    For any Customer and any set of Actions, ``assign_actions`` succeeds iff
    every Action's parent Module is currently subscribed; if any Action's Module
    is unsubscribed the whole assignment is rejected and the role's existing
    Actions are left unchanged.

Property 16 — **Validates: Requirements 8.4, 8.6, 7.8**
    For any Customer and Module, removing/expiring the Module leaves the
    custom-role Action definitions unchanged (rejection is atomic), and re-adding
    the Module restores those same Actions to usability (assignable again).

These are pure-logic property tests. The database boundary is an in-memory fake
``AsyncSession`` backed by an in-memory ``_World`` graph, mirroring the fakes in
``tests/unit/test_authorization_service_custom_roles.py`` and
``tests/unit/test_authorization_service_assign_actions.py``. It interprets the
specific query shapes the service issues:

* ``select(Role.id).where(...)``                        → name-availability
* ``select(Role).where(...)``                           → role lookup
* ``select(RolePermission.action_id).where(...)``       → clone copy
* ``select(RolePermission).where(...)``                 → existing grants
* ``select(Action.id, SubModule.module_id).join(...)``  → module resolution
* ``select(status, expires_at).where(CustomerSubscription...)`` → usability

No real database is touched. Each property runs a minimum of 100 iterations.
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.errors import (
    ActionModuleUnsubscribedError,
    NotAuthorizedError,
    RoleNameConflictError,
    ValidationError,
)
from app.core.tenant_context import TenantContext
from app.models.permission import Action, Resource, SubModule
from app.models.role import Role, RolePermission
from app.models.subscription import CustomerSubscription
from app.services.authorization_service import AuthorizationService

pytestmark = pytest.mark.asyncio

NOW = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# In-memory permission-graph + subscription world (shared shape with the
# unit-test fakes in tests/unit/test_authorization_service_*).
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
        self.action_module: dict[UUID, UUID] = {}
        self.subscriptions: dict[tuple[UUID, UUID], tuple] = {}

    def add_role(self, role: Role) -> None:
        self.roles.append(role)

    def add_action(self, action_id: UUID, module_id: UUID) -> None:
        self.action_module[action_id] = module_id

    def subscribe(self, customer_id, module_id, status="active", expires_at=None):
        self.subscriptions[(customer_id, module_id)] = (status, expires_at)

    def unsubscribe(self, customer_id, module_id) -> None:
        self.subscriptions.pop((customer_id, module_id), None)


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


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


class _FakeSession:
    """AsyncSession stand-in backed by an in-memory ``_World``.

    Combines the query-shape handling of both unit-test fakes so the same
    session serves create/clone/assign/usability flows.
    """

    def __init__(self, world: _World) -> None:
        self.world = world
        self._pending: list = []
        self.rolled_back = False

    # -- SQLAlchemy-like surface -------------------------------------------

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
            if isinstance(obj, RolePermission) and obj not in self.world.permissions:
                self.world.permissions.append(obj)
            elif isinstance(obj, Role) and obj not in self.world.roles:
                self.world.roles.append(obj)
        self._pending = []

    async def rollback(self) -> None:
        self.rolled_back = True
        self._pending = []

    async def execute(self, statement):  # noqa: ANN001
        descs = statement.column_descriptions
        entities = {d["entity"] for d in descs}

        # is_module_usable: select(status, expires_at) from CustomerSubscription
        if CustomerSubscription in entities:
            cust_id, mod_id = self._extract_kv(statement, ("customer_id", "module_id"))
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

        first_entity = descs[0]["entity"]
        first_expr = descs[0]["expr"]

        # Role queries: select(Role) (lookup) or select(Role.id) (name check).
        if first_entity is Role:
            candidates = [
                r for r in self.world.roles if self._matches(statement, r)
            ]
            if first_expr is Role:
                return _Result(candidates, scalar_rows=candidates)
            return _Result([(r.id,) for r in candidates])

        # RolePermission queries: select(RolePermission) (grants) or
        # select(RolePermission.action_id) (clone copy).
        if first_entity is RolePermission:
            candidates = [
                p for p in self.world.permissions if self._matches(statement, p)
            ]
            if first_expr is RolePermission:
                return _Result(candidates, scalar_rows=candidates)
            return _Result(
                [(p.action_id,) for p in candidates],
                scalar_rows=[p.action_id for p in candidates],
            )

        raise AssertionError(f"unexpected statement entities: {entities}")

    # -- WHERE-clause evaluation (generic, matches the custom-roles fake) --

    @staticmethod
    def _matches(statement, row) -> bool:
        whereclause = statement.whereclause
        if whereclause is None:
            return True
        return _FakeSession._eval(whereclause, row)

    @staticmethod
    def _eval(clause, row) -> bool:
        from sqlalchemy.sql import operators

        if hasattr(clause, "clauses") and clause.clauses:
            results = [_FakeSession._eval(c, row) for c in clause.clauses]
            if clause.operator is operators.or_:
                return any(results)
            return all(results)

        op = getattr(clause, "operator", None)
        left = getattr(clause, "left", None)
        right = getattr(clause, "right", None)
        if left is None or op is None:
            raise AssertionError(f"cannot evaluate clause: {clause!r}")

        col_name = left.key
        actual = getattr(row, col_name)
        expected = getattr(right, "value", right)

        if op in (operators.eq, operators.is_):
            return actual == expected
        if op in (operators.ne, operators.is_not):
            return actual != expected
        raise AssertionError(f"unsupported operator in fake: {op!r}")

    # -- crude filter extraction (matches the assign-actions fake) ---------

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

    def _extract_kv(self, statement, keys):
        found = {k: None for k in keys}
        for b in self._iter_binary(statement.whereclause):
            key = getattr(b.left, "key", None)
            if key in found:
                found[key] = getattr(b.right, "value", None)
        return tuple(found[k] for k in keys)

    def _extract_in_values(self, statement):
        for b in self._iter_binary(statement.whereclause):
            val = getattr(b.right, "value", None)
            if isinstance(val, (list, tuple)):
                return list(val)
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service(world: _World) -> AuthorizationService:
    return AuthorizationService(_FakeSession(world), now=lambda: NOW)


def _ctx(customer_id) -> TenantContext:
    """A customeradmin-like context scoped to a single customer."""
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


def _custom_role(customer_id, name) -> Role:
    r = Role(role_type=None, is_custom=True, customer_id=customer_id, name=name)
    r.id = uuid4()
    return r


def _grants_for(world: _World, role_id) -> set:
    return {p.action_id for p in world.permissions if p.role_id == role_id}


# Role-name strategies.
# A valid name is 1..100 chars once trimmed; we keep interior chars non-space
# so trimming length is predictable, and avoid names that collapse to empty.
_valid_name_core = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp")),
    min_size=1,
    max_size=100,
).filter(lambda s: 1 <= len(s.strip()) <= 100 and len(s.strip()) > 0)


# ===========================================================================
# Property 12: Custom role name scoping and uniqueness (Req 7.2)
# ===========================================================================


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(name=_valid_name_core)
async def test_p12_valid_name_creates_role_scoped_to_customer(name):
    """A valid, unique name creates a custom role scoped to that one customer."""
    customer = uuid4()
    world = _World()
    svc = _service(world)

    role = await svc.create_custom_role(_ctx(customer), customer, name)

    assert role.is_custom is True
    assert role.role_type is None
    assert role.customer_id == customer
    assert role.name == name.strip()
    assert role in world.roles


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(name=_valid_name_core)
async def test_p12_duplicate_name_within_customer_is_rejected(name):
    """A second role with the same trimmed name in the same customer is rejected."""
    customer = uuid4()
    world = _World()
    world.add_role(_custom_role(customer, name.strip()))
    svc = _service(world)

    with pytest.raises(RoleNameConflictError):
        await svc.create_custom_role(_ctx(customer), customer, name)

    # The conflicting create left the single existing role in place.
    assert sum(1 for r in world.roles if r.name == name.strip()) == 1


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(name=_valid_name_core)
async def test_p12_same_name_allowed_across_customers(name):
    """The same name is allowed for a different customer (per-customer scoping)."""
    customer_a = uuid4()
    customer_b = uuid4()
    world = _World()
    world.add_role(_custom_role(customer_a, name.strip()))
    svc = _service(world)

    role = await svc.create_custom_role(_ctx(customer_b), customer_b, name)

    assert role.customer_id == customer_b
    assert role.name == name.strip()


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(overflow=st.integers(min_value=101, max_value=400))
async def test_p12_name_too_long_is_rejected(overflow):
    """A trimmed length above 100 characters is rejected (upper bound)."""
    customer = uuid4()
    svc = _service(_World())
    with pytest.raises(ValidationError):
        await svc.create_custom_role(_ctx(customer), customer, "x" * overflow)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pad=st.text(alphabet=" \t\n", min_size=0, max_size=10))
async def test_p12_whitespace_only_name_is_rejected(pad):
    """A name that trims to empty (below the 1-char lower bound) is rejected."""
    customer = uuid4()
    svc = _service(_World())
    with pytest.raises(ValidationError):
        await svc.create_custom_role(_ctx(customer), customer, pad)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(length=st.integers(min_value=1, max_value=100))
async def test_p12_boundary_lengths_are_accepted(length):
    """Trimmed lengths on the inclusive 1..100 boundary are accepted."""
    customer = uuid4()
    svc = _service(_World())
    role = await svc.create_custom_role(_ctx(customer), customer, "a" * length)
    assert len(role.name) == length


# ===========================================================================
# Property 13: Custom role clone preserves action set (Req 7.4)
# ===========================================================================


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    n_actions=st.integers(min_value=0, max_value=12),
    new_name=_valid_name_core,
)
async def test_p13_clone_action_set_equals_source(n_actions, new_name):
    """The clone's assigned-action set equals the source's, exactly."""
    customer = uuid4()
    world = _World()
    source = _custom_role(customer, "Source")
    world.add_role(source)
    source_actions = {uuid4() for _ in range(n_actions)}
    for aid in source_actions:
        world.permissions.append(RolePermission(role_id=source.id, action_id=aid))

    # Ensure the new name doesn't collide with the fixed source name.
    normalized_new = new_name.strip()
    if normalized_new == "Source":
        normalized_new = "Source Copy"

    svc = _service(world)
    clone = await svc.clone_custom_role(_ctx(customer), source.id, normalized_new)

    assert clone.id != source.id
    assert clone.customer_id == customer
    assert clone.is_custom is True
    assert clone.name == normalized_new
    # Action set identical to the source (Req 7.4).
    assert _grants_for(world, clone.id) == source_actions
    # Source's own grants are untouched by the clone.
    assert _grants_for(world, source.id) == source_actions


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n_actions=st.integers(min_value=1, max_value=8))
async def test_p13_clone_then_add_and_remove_actions(n_actions):
    """A clone can subsequently have actions added and removed (Req 7.4)."""
    customer = uuid4()
    module = uuid4()
    world = _World()
    source = _custom_role(customer, "Source")
    world.add_role(source)
    source_actions = [uuid4() for _ in range(n_actions)]
    for aid in source_actions:
        world.add_action(aid, module)
        world.permissions.append(RolePermission(role_id=source.id, action_id=aid))
    world.subscribe(customer, module)

    svc = _service(world)
    clone = await svc.clone_custom_role(_ctx(customer), source.id, "Clone")
    assert _grants_for(world, clone.id) == set(source_actions)

    # Add a new action to the clone.
    extra = uuid4()
    world.add_action(extra, module)
    await svc.assign_actions(_ctx(customer), clone.id, source_actions + [extra])
    assert _grants_for(world, clone.id) == set(source_actions) | {extra}

    # Remove everything from the clone (subscribed module -> allowed).
    await svc.assign_actions(_ctx(customer), clone.id, [])
    assert _grants_for(world, clone.id) == set()


# ===========================================================================
# Property 14: Action assignment limited to subscribed modules
# (Req 7.5, 7.6, 7.7, 7.9)
# ===========================================================================


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    n_subscribed=st.integers(min_value=0, max_value=4),
    n_unsubscribed=st.integers(min_value=0, max_value=4),
    n_existing=st.integers(min_value=0, max_value=4),
)
async def test_p14_assign_succeeds_iff_all_modules_subscribed(
    n_subscribed, n_unsubscribed, n_existing
):
    """assign_actions succeeds iff every requested action's module is subscribed;
    on rejection the role's existing actions are unchanged (Req 7.5, 7.6, 7.9)."""
    customer = uuid4()
    sub_module = uuid4()
    unsub_module = uuid4()
    world = _World()
    role = _custom_role(customer, "Role")
    world.add_role(role)
    world.subscribe(customer, sub_module)  # unsub_module deliberately absent

    subscribed_actions = [uuid4() for _ in range(n_subscribed)]
    for aid in subscribed_actions:
        world.add_action(aid, sub_module)
    unsubscribed_actions = [uuid4() for _ in range(n_unsubscribed)]
    for aid in unsubscribed_actions:
        world.add_action(aid, unsub_module)

    # Seed some pre-existing grants (from the subscribed module so they are
    # legitimate) that must survive any rejection.
    existing_actions = [uuid4() for _ in range(n_existing)]
    for aid in existing_actions:
        world.add_action(aid, sub_module)
        world.permissions.append(RolePermission(role_id=role.id, action_id=aid))
    existing_set = set(existing_actions)

    requested = subscribed_actions + unsubscribed_actions
    svc = _service(world)

    if unsubscribed_actions:
        # At least one action from an unsubscribed module -> whole thing rejected.
        with pytest.raises(ActionModuleUnsubscribedError):
            await svc.assign_actions(_ctx(customer), role.id, requested)
        # Req 7.6 — existing actions unchanged; no partial application.
        assert _grants_for(world, role.id) == existing_set
    else:
        # Every requested action's module is subscribed -> success (Req 7.5).
        await svc.assign_actions(_ctx(customer), role.id, requested)
        assert _grants_for(world, role.id) == set(subscribed_actions)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n_actions=st.integers(min_value=1, max_value=6))
async def test_p14_expired_module_action_is_rejected(n_actions):
    """Actions from an active-but-expired module are rejected (non-usable)."""
    customer = uuid4()
    module = uuid4()
    world = _World()
    role = _custom_role(customer, "Role")
    world.add_role(role)
    actions = [uuid4() for _ in range(n_actions)]
    for aid in actions:
        world.add_action(aid, module)
    world.subscribe(customer, module, expires_at=NOW - datetime.timedelta(seconds=1))

    svc = _service(world)
    with pytest.raises(ActionModuleUnsubscribedError):
        await svc.assign_actions(_ctx(customer), role.id, actions)
    assert _grants_for(world, role.id) == set()


# ===========================================================================
# Property 16: Subscription add/remove round-trip preserves definitions
# (Req 8.4, 8.6, 7.8)
# ===========================================================================


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n_actions=st.integers(min_value=1, max_value=8))
async def test_p16_remove_then_readd_restores_usability_and_definitions(n_actions):
    """Removing then re-adding a module leaves the role's action definitions
    intact and restores those actions to usability/assignability (Req 8.4/8.6/7.8)."""
    customer = uuid4()
    module = uuid4()
    world = _World()
    role = _custom_role(customer, "Role")
    world.add_role(role)
    actions = [uuid4() for _ in range(n_actions)]
    for aid in actions:
        world.add_action(aid, module)
    world.subscribe(customer, module)

    svc = _service(world)

    # 1. Assign while subscribed -> succeeds and module is usable.
    await svc.assign_actions(_ctx(customer), role.id, actions)
    assert _grants_for(world, role.id) == set(actions)
    assert await svc.is_module_usable(customer, module) is True

    grants_before = _grants_for(world, role.id)

    # 2. Remove the module -> its actions become non-usable, but the role's
    #    existing definition rows are retained untouched (Req 8.6, 7.8).
    world.unsubscribe(customer, module)
    assert await svc.is_module_usable(customer, module) is False
    assert _grants_for(world, role.id) == grants_before  # definitions unchanged

    # While removed, re-assigning the same actions is rejected atomically and
    # still leaves the retained definition unchanged (Req 7.8).
    with pytest.raises(ActionModuleUnsubscribedError):
        await svc.assign_actions(_ctx(customer), role.id, actions)
    assert _grants_for(world, role.id) == grants_before

    # 3. Re-add the module -> same actions restored to usability/assignability
    #    (Req 8.4). The definition is exactly what it was before removal.
    world.subscribe(customer, module)
    assert await svc.is_module_usable(customer, module) is True
    await svc.assign_actions(_ctx(customer), role.id, actions)
    assert _grants_for(world, role.id) == grants_before


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    n_actions=st.integers(min_value=1, max_value=6),
    expire=st.booleans(),
)
async def test_p16_expiry_matches_removal_roundtrip(n_actions, expire):
    """Expiring a module behaves like removing it for the round-trip: actions
    become non-usable while definitions persist, and renewal restores them."""
    customer = uuid4()
    module = uuid4()
    world = _World()
    role = _custom_role(customer, "Role")
    world.add_role(role)
    actions = [uuid4() for _ in range(n_actions)]
    for aid in actions:
        world.add_action(aid, module)
    world.subscribe(customer, module)

    svc = _service(world)
    await svc.assign_actions(_ctx(customer), role.id, actions)
    grants_before = _grants_for(world, role.id)

    # Make the module non-usable either by expiry or by removal.
    if expire:
        world.subscribe(
            customer, module, expires_at=NOW - datetime.timedelta(seconds=1)
        )
    else:
        world.unsubscribe(customer, module)

    assert await svc.is_module_usable(customer, module) is False
    assert _grants_for(world, role.id) == grants_before  # retained

    # Restore (renew / re-add) -> usable again, same definitions assignable.
    world.subscribe(customer, module)
    assert await svc.is_module_usable(customer, module) is True
    await svc.assign_actions(_ctx(customer), role.id, actions)
    assert _grants_for(world, role.id) == grants_before

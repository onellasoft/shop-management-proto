"""Unit tests for AuthorizationService custom-role management (Task 11.1).

Covers ``create_custom_role``, ``clone_custom_role``, ``update_custom_role``,
and ``delete_custom_role`` (Req 7.2, 7.3, 7.4).

These are pure-logic tests: the database boundary is an in-memory fake
``AsyncSession`` that stores ``Role`` and ``RolePermission`` ORM instances in
Python lists and interprets the specific query shapes the service issues:

* ``select(Role.id).where(...)``   → name-availability check → ``.first()``
* ``select(Role).where(...)``      → role lookup            → ``.scalar_one_or_none()``
* ``select(RolePermission.action_id).where(...)`` → clone copy → ``.scalars().all()``
* ``select(RolePermission).where(...)``           → delete grants → ``.scalars().all()``

The fake evaluates each statement's compiled WHERE clause against the stored
rows via SQLAlchemy's own column accessors, so the tests exercise the real
filtering logic in the service without needing a live database (the models use
Postgres-specific types/constraints that will not run on SQLite).
"""

from __future__ import annotations

import uuid
from uuid import uuid4

import pytest

from app.core.errors import (
    NotAuthorizedError,
    RoleNameConflictError,
    ValidationError,
)
from app.core.tenant_context import TenantContext
from app.models.role import Role, RolePermission
from app.services.authorization_service import AuthorizationService


# ---------------------------------------------------------------------------
# In-memory fake AsyncSession
# ---------------------------------------------------------------------------


class _ScalarResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _Result:
    """Minimal Result stub supporting the accessors the service uses."""

    def __init__(self, rows: list, *, scalar_rows: list | None = None) -> None:
        # ``rows`` are tuple-like rows (for .first()); ``scalar_rows`` are the
        # single-column scalar values (for .scalars()/.scalar_one_or_none()).
        self._rows = rows
        self._scalar_rows = scalar_rows if scalar_rows is not None else rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._scalar_rows)

    def scalar_one_or_none(self):
        if not self._scalar_rows:
            return None
        if len(self._scalar_rows) > 1:
            raise AssertionError("scalar_one_or_none matched multiple rows")
        return self._scalar_rows[0]


class _FakeSession:
    """AsyncSession stand-in backed by in-memory lists of ORM instances."""

    def __init__(
        self,
        roles: list[Role] | None = None,
        permissions: list[RolePermission] | None = None,
        *,
        flush_raises=None,
    ) -> None:
        self.roles: list[Role] = list(roles or [])
        self.permissions: list[RolePermission] = list(permissions or [])
        self._pending: list = []
        self.flush_calls = 0
        self._flush_raises = flush_raises
        self.rolled_back = False

    # -- SQLAlchemy-like surface -------------------------------------------

    def add(self, obj) -> None:
        # Assign a primary key like a DB default would on flush.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._pending.append(obj)

    async def delete(self, obj) -> None:
        if isinstance(obj, Role) and obj in self.roles:
            self.roles.remove(obj)
        elif isinstance(obj, RolePermission) and obj in self.permissions:
            self.permissions.remove(obj)

    async def flush(self) -> None:
        self.flush_calls += 1
        if self._flush_raises is not None:
            exc = self._flush_raises
            self._flush_raises = None  # only raise once
            raise exc
        for obj in self._pending:
            if isinstance(obj, Role) and obj not in self.roles:
                self.roles.append(obj)
            elif isinstance(obj, RolePermission) and obj not in self.permissions:
                self.permissions.append(obj)
        self._pending = []

    async def rollback(self) -> None:
        self.rolled_back = True
        self._pending = []

    async def execute(self, statement):  # noqa: ANN001
        desc = statement.column_descriptions[0]
        entity = desc["entity"]
        expr = desc["expr"]

        if entity is Role:
            candidates = [r for r in self.roles if self._matches(statement, r)]
            if expr is Role:
                # select(Role) -> scalar rows are Role instances
                return _Result(candidates, scalar_rows=candidates)
            # select(Role.id) -> tuple rows carrying the id
            return _Result([(r.id,) for r in candidates])

        if entity is RolePermission:
            candidates = [
                p for p in self.permissions if self._matches(statement, p)
            ]
            if expr is RolePermission:
                return _Result(candidates, scalar_rows=candidates)
            # select(RolePermission.action_id) -> scalars are action_ids
            return _Result(
                [(p.action_id,) for p in candidates],
                scalar_rows=[p.action_id for p in candidates],
            )

        raise AssertionError(f"unexpected entity in statement: {entity}")

    # -- WHERE-clause evaluation -------------------------------------------

    @staticmethod
    def _matches(statement, row) -> bool:
        """Evaluate the statement's WHERE clause against a single ORM row."""
        whereclause = statement.whereclause
        if whereclause is None:
            return True
        return _FakeSession._eval(whereclause, row)

    @staticmethod
    def _eval(clause, row) -> bool:
        from sqlalchemy.sql import operators

        # BooleanClauseList (AND/OR of children)
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

        # right may be a bound param (value) or a literal True/False (is_(True)).
        expected = getattr(right, "value", right)

        if op in (operators.eq, operators.is_):
            return actual == expected
        if op in (operators.ne, operators.is_not):
            return actual != expected
        raise AssertionError(f"unsupported operator in fake: {op!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service(session) -> AuthorizationService:
    return AuthorizationService(session)


def _ctx(customer_id, *, custom_role: bool = False) -> TenantContext:
    """Build a customeradmin-like context scoped to a single customer."""
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
        custom_role_customer_id=customer_id if custom_role else None,
    )


def _custom_role(customer_id, name, *, role_id=None) -> Role:
    r = Role(role_type=None, is_custom=True, customer_id=customer_id, name=name)
    r.id = role_id or uuid4()
    return r


# ===========================================================================
# create_custom_role (Req 7.2, 7.3)
# ===========================================================================


async def test_create_custom_role_persists_scoped_custom_role():
    customer = uuid4()
    session = _FakeSession()
    svc = _service(session)

    role = await svc.create_custom_role(_ctx(customer), customer, "Finance")

    assert role.is_custom is True
    assert role.customer_id == customer
    assert role.name == "Finance"
    assert role.role_type is None
    assert role in session.roles


async def test_create_custom_role_trims_whitespace():
    customer = uuid4()
    svc = _service(_FakeSession())
    role = await svc.create_custom_role(_ctx(customer), customer, "  Staff  ")
    assert role.name == "Staff"


async def test_create_custom_role_rejects_empty_name():
    customer = uuid4()
    svc = _service(_FakeSession())
    with pytest.raises(ValidationError):
        await svc.create_custom_role(_ctx(customer), customer, "   ")


async def test_create_custom_role_rejects_name_over_100_chars():
    customer = uuid4()
    svc = _service(_FakeSession())
    with pytest.raises(ValidationError):
        await svc.create_custom_role(_ctx(customer), customer, "x" * 101)


async def test_create_custom_role_accepts_boundary_lengths():
    customer = uuid4()
    svc = _service(_FakeSession())
    one = await svc.create_custom_role(_ctx(customer), customer, "a")
    hundred = await svc.create_custom_role(_ctx(customer), customer, "b" * 100)
    assert one.name == "a"
    assert len(hundred.name) == 100


async def test_create_custom_role_rejects_duplicate_name_within_customer():
    customer = uuid4()
    session = _FakeSession(roles=[_custom_role(customer, "Finance")])
    svc = _service(session)
    with pytest.raises(RoleNameConflictError):
        await svc.create_custom_role(_ctx(customer), customer, "Finance")


async def test_create_custom_role_allows_same_name_in_different_customer():
    customer_a = uuid4()
    customer_b = uuid4()
    session = _FakeSession(roles=[_custom_role(customer_a, "Finance")])
    svc = _service(session)
    role = await svc.create_custom_role(_ctx(customer_b), customer_b, "Finance")
    assert role.customer_id == customer_b


# ===========================================================================
# clone_custom_role (Req 7.4)
# ===========================================================================


async def test_clone_copies_action_set_and_new_name():
    customer = uuid4()
    source = _custom_role(customer, "Finance")
    a1, a2 = uuid4(), uuid4()
    perms = [
        RolePermission(role_id=source.id, action_id=a1),
        RolePermission(role_id=source.id, action_id=a2),
    ]
    session = _FakeSession(roles=[source], permissions=perms)
    svc = _service(session)

    clone = await svc.clone_custom_role(_ctx(customer), source.id, "Finance Copy")

    assert clone.id != source.id
    assert clone.name == "Finance Copy"
    assert clone.customer_id == customer
    assert clone.is_custom is True
    cloned_actions = {
        p.action_id for p in session.permissions if p.role_id == clone.id
    }
    assert cloned_actions == {a1, a2}


async def test_clone_with_no_actions_copies_empty_set():
    customer = uuid4()
    source = _custom_role(customer, "Empty")
    session = _FakeSession(roles=[source])
    svc = _service(session)

    clone = await svc.clone_custom_role(_ctx(customer), source.id, "Empty Copy")

    cloned_actions = [p for p in session.permissions if p.role_id == clone.id]
    assert cloned_actions == []


async def test_clone_rejects_duplicate_new_name():
    customer = uuid4()
    source = _custom_role(customer, "Finance")
    existing = _custom_role(customer, "Taken")
    session = _FakeSession(roles=[source, existing])
    svc = _service(session)
    with pytest.raises(RoleNameConflictError):
        await svc.clone_custom_role(_ctx(customer), source.id, "Taken")


async def test_clone_rejects_source_outside_customer_scope():
    customer = uuid4()
    other_customer = uuid4()
    source = _custom_role(other_customer, "Finance")
    session = _FakeSession(roles=[source])
    svc = _service(session)
    with pytest.raises(NotAuthorizedError):
        await svc.clone_custom_role(_ctx(customer), source.id, "Copy")


async def test_clone_rejects_invalid_new_name():
    customer = uuid4()
    source = _custom_role(customer, "Finance")
    svc = _service(_FakeSession(roles=[source]))
    with pytest.raises(ValidationError):
        await svc.clone_custom_role(_ctx(customer), source.id, "")


# ===========================================================================
# update_custom_role (Req 7.3)
# ===========================================================================


async def test_update_renames_custom_role():
    customer = uuid4()
    role = _custom_role(customer, "Old")
    session = _FakeSession(roles=[role])
    svc = _service(session)

    updated = await svc.update_custom_role(_ctx(customer), role.id, name="New")
    assert updated.name == "New"


async def test_update_same_name_is_noop_and_allowed():
    customer = uuid4()
    role = _custom_role(customer, "Same")
    session = _FakeSession(roles=[role])
    svc = _service(session)
    updated = await svc.update_custom_role(_ctx(customer), role.id, name="Same")
    assert updated.name == "Same"


async def test_update_rejects_conflicting_name():
    customer = uuid4()
    role = _custom_role(customer, "Old")
    other = _custom_role(customer, "Taken")
    session = _FakeSession(roles=[role, other])
    svc = _service(session)
    with pytest.raises(RoleNameConflictError):
        await svc.update_custom_role(_ctx(customer), role.id, name="Taken")


async def test_update_rejects_invalid_length():
    customer = uuid4()
    role = _custom_role(customer, "Old")
    svc = _service(_FakeSession(roles=[role]))
    with pytest.raises(ValidationError):
        await svc.update_custom_role(_ctx(customer), role.id, name="x" * 101)


async def test_update_rejects_role_outside_customer_scope():
    customer = uuid4()
    role = _custom_role(uuid4(), "Old")
    svc = _service(_FakeSession(roles=[role]))
    with pytest.raises(NotAuthorizedError):
        await svc.update_custom_role(_ctx(customer), role.id, name="New")


async def test_update_without_name_returns_role_unchanged():
    customer = uuid4()
    role = _custom_role(customer, "Keep")
    svc = _service(_FakeSession(roles=[role]))
    updated = await svc.update_custom_role(_ctx(customer), role.id)
    assert updated.name == "Keep"


# ===========================================================================
# delete_custom_role (Req 7.3)
# ===========================================================================


async def test_delete_removes_role_and_its_grants():
    customer = uuid4()
    role = _custom_role(customer, "Finance")
    perms = [
        RolePermission(role_id=role.id, action_id=uuid4()),
        RolePermission(role_id=role.id, action_id=uuid4()),
    ]
    session = _FakeSession(roles=[role], permissions=perms)
    svc = _service(session)

    await svc.delete_custom_role(_ctx(customer), role.id)

    assert role not in session.roles
    assert [p for p in session.permissions if p.role_id == role.id] == []


async def test_delete_rejects_role_outside_customer_scope():
    customer = uuid4()
    role = _custom_role(uuid4(), "Finance")
    svc = _service(_FakeSession(roles=[role]))
    with pytest.raises(NotAuthorizedError):
        await svc.delete_custom_role(_ctx(customer), role.id)


async def test_delete_rejects_unknown_role():
    customer = uuid4()
    svc = _service(_FakeSession())
    with pytest.raises(NotAuthorizedError):
        await svc.delete_custom_role(_ctx(customer), uuid4())


# ===========================================================================
# customer scope resolution (Req 7.3)
# ===========================================================================


async def test_clone_uses_custom_role_customer_scope_when_present():
    customer = uuid4()
    source = _custom_role(customer, "Finance")
    session = _FakeSession(roles=[source])
    svc = _service(session)
    clone = await svc.clone_custom_role(
        _ctx(customer, custom_role=True), source.id, "Copy"
    )
    assert clone.customer_id == customer


async def test_operation_rejected_when_scope_ambiguous():
    customer_a = uuid4()
    customer_b = uuid4()
    ctx = TenantContext(
        user_id=uuid4(),
        role_type="customeradmin",
        agency_scope=None,
        customer_scope=frozenset({customer_a, customer_b}),
        is_superadmin=False,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )
    role = _custom_role(customer_a, "Finance")
    svc = _service(_FakeSession(roles=[role]))
    with pytest.raises(NotAuthorizedError):
        await svc.update_custom_role(ctx, role.id, name="New")

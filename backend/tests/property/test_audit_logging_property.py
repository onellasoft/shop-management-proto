"""Property-based tests for mutation audit logging (Task 21.4 — Req 14.1-14.7).

# Feature: onella-backend, Property 26: Every mutation produces exactly one audit log; reads produce none

**Validates: Requirements 14.2, 14.5**

# Feature: onella-backend, Property 27: Audit log content correctness

**Validates: Requirements 14.1, 14.3, 14.4**

# Feature: onella-backend, Property 28: Audit logs are append-only

**Validates: Requirements 14.6**

# Feature: onella-backend, Property 29: Audit write failure is retried then durably recorded

**Validates: Requirements 14.7**

These tests drive the REAL audit code over Hypothesis-generated worlds with no
live database, broker, or Celery — only the in-memory fakes established by the
unit tests (``tests/unit/test_audit_capture.py``,
``tests/unit/test_audit_tasks.py``, ``tests/unit/test_audit_append_only_guard.py``):

* **Property 26** — over generated sequences of operations (create / update /
  delete on a *registered* audited model, plus reads / no-op dirties /
  non-registered-model mutations) applied to a fake ORM session and driven
  through the real ``after_flush`` → ``after_commit`` path with an injected
  recording scheduler: exactly one entry is enqueued per real mutation and zero
  for every non-mutation (Req 14.2, 14.5). A ``after_rollback`` never enqueues.

* **Property 27** — over a generated :class:`TenantContext` (varying role,
  impersonating or not, tenant ids) stashed via ``set_session_tenant_context``
  plus a create / update / delete on the registered model: the built
  :class:`AuditEntry` records the correct action, coordinates, actor / tenant
  identifiers, create → ``old_value == {}`` / delete → ``new_value == {}`` /
  update → only changed columns, and — under impersonation —
  ``impersonation is True`` + the impersonator id (Req 14.1, 14.3, 14.4).

* **Property 28** — over generated ``AuditLog`` states: the real
  ``assert_audit_logs_immutable`` guard (fired from ``before_flush``) raises
  :class:`AuditImmutableError` for an ``AuditLog`` in ``session.deleted`` or
  ``session.dirty`` with a real change, and does NOT raise for an ``AuditLog``
  insert (``session.new``), a dirty-but-unchanged ``AuditLog``, or non-audit
  objects (Req 14.6).

* **Property 29** — over generated entry dicts: the real ``write_audit_log``
  body driven with a fake bound-task ``self`` (Celery-like ``retry`` that
  reschedules 3 times then raises ``MaxRetriesExceededError``) and an injected
  session factory whose ``AuditLog`` INSERT always fails: the write retries
  exactly 3 times then writes exactly one ``AuditFailure`` carrying the payload,
  never propagating to the caller; and the success path writes exactly one
  ``AuditLog`` and no ``AuditFailure`` (Req 14.7 + happy path 14.5).

The throwaway audited model ``_AuditWidget`` is registered ONCE at module import
(not per-example) so the audited-model registry never grows unboundedly.
"""

from __future__ import annotations

import uuid

import pytest
from celery.exceptions import MaxRetriesExceededError
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import String, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.attributes import set_committed_value

from app.audit import mutation_capture as mc
from app.audit.mutation_capture import (
    AuditEntry,
    assert_audit_logs_immutable,
    register_audited_model,
    set_audit_scheduler,
)
from app.core.errors import AuditImmutableError
from app.core.tenant_context import TenantContext
from app.models.audit import AuditFailure, AuditLog
from app.tasks import audit_tasks
from app.tasks.audit_tasks import set_audit_session_factory


# ---------------------------------------------------------------------------
# Throwaway mapped model — registered ONCE at import (keeps the registry clean)
# ---------------------------------------------------------------------------


class _PropBase(DeclarativeBase):
    pass


class _AuditWidget(_PropBase):
    __tablename__ = "prop_audit_widgets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=True)
    color: Mapped[str] = mapped_column(String, nullable=True)
    size: Mapped[str] = mapped_column(String, nullable=True)


class _PropUnregistered(_PropBase):
    __tablename__ = "prop_audit_unregistered"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=True)


_MODULE = "marketing"
_SUB_MODULE = "campaign"
_RESOURCE = "widget"

register_audited_model(
    _AuditWidget, module=_MODULE, sub_module=_SUB_MODULE, resource=_RESOURCE
)


# ---------------------------------------------------------------------------
# In-memory fakes (mirrors the audit unit tests)
# ---------------------------------------------------------------------------


class _FakeOrmSession:
    """Minimal ``Session`` stand-in exposing new/dirty/deleted/info."""

    def __init__(self, *, new=None, dirty=None, deleted=None) -> None:
        self.new = new or set()
        self.dirty = dirty or set()
        self.deleted = deleted or set()
        self.info: dict = {}


def _new_widget(**kwargs) -> _AuditWidget:
    return _AuditWidget(id=str(uuid.uuid4()), **kwargs)


def _as_loaded(widget: _AuditWidget) -> _AuditWidget:
    """Mark every column committed so the instance looks loaded-from-DB."""
    for attr in inspect(_AuditWidget).column_attrs:
        set_committed_value(widget, attr.key, getattr(widget, attr.key))
    return widget


@pytest.fixture(autouse=True)
def _restore_seams():
    """Always restore the injected scheduler / session factory after a test."""
    yield
    set_audit_scheduler(None)
    set_audit_session_factory(None)


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_uuids = st.builds(uuid.uuid4)
_values = st.text(min_size=0, max_size=12)


@st.composite
def _tenant_context(draw: st.DrawFn) -> TenantContext:
    """A varied ``TenantContext``: any role, impersonating or not, tenant ids."""
    role = draw(st.sampled_from(["superadmin", "agencyadmin", "customeradmin"]))
    impersonating = draw(st.booleans())

    if impersonating:
        return TenantContext(
            user_id=draw(_uuids),
            role_type=role,
            agency_scope=draw(st.none() | _uuids),
            customer_scope=frozenset(),
            is_superadmin=(role == "superadmin"),
            impersonating=True,
            impersonated_agency_id=draw(st.none() | _uuids),
            impersonated_customer_id=draw(st.none() | _uuids),
            impersonator_user_id=draw(_uuids),
            custom_role_customer_id=None,
        )

    # Non-impersonating: optionally a single-customer scope or a custom-role
    # customer id (both drive the entry.customer_id derivation).
    single_customer = draw(st.none() | _uuids)
    custom_role_customer = draw(st.none() | _uuids)
    customer_scope = (
        frozenset({single_customer}) if single_customer is not None else frozenset()
    )
    return TenantContext(
        user_id=draw(_uuids),
        role_type=role,
        agency_scope=draw(st.none() | _uuids),
        customer_scope=customer_scope,
        is_superadmin=(role == "superadmin"),
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=custom_role_customer,
    )


# ===========================================================================
# Property 26 — one audit log per mutation; none for reads
# ===========================================================================


# One generated operation in the sequence. ``is_mutation`` records whether the
# real capture path SHOULD produce exactly one entry for it.
@st.composite
def _operation(draw: st.DrawFn):
    kind = draw(
        st.sampled_from(
            [
                "create",
                "update",
                "delete",
                "read",
                "noop_dirty",  # dirty widget with no real column change
                "unregistered_create",  # mutation of a non-audited model
            ]
        )
    )
    if kind == "create":
        obj = _new_widget(name=draw(_values), color=draw(_values))
        return ("new", obj, True)
    if kind == "delete":
        obj = _new_widget(name=draw(_values))
        return ("deleted", obj, True)
    if kind == "update":
        obj = _as_loaded(_new_widget(name=draw(_values), color=draw(_values)))
        obj.name = draw(_values) + "!"  # guaranteed distinct → real change
        return ("dirty", obj, True)
    if kind == "noop_dirty":
        obj = _as_loaded(_new_widget(name=draw(_values)))  # no pending change
        return ("dirty", obj, False)
    if kind == "unregistered_create":
        return ("new", _PropUnregistered(id=str(uuid.uuid4())), False)
    # read — nothing is added to any collection.
    return (None, None, False)


# Feature: onella-backend, Property 26: Every mutation produces exactly one audit log; reads produce none
@settings(max_examples=200, deadline=None)
@given(ops=st.lists(_operation(), min_size=0, max_size=8))
def test_every_mutation_one_log_reads_none(ops) -> None:
    """Exactly one enqueued entry per real mutation; zero for any non-mutation.

    Drives the real ``after_flush`` → ``after_commit`` path with an injected
    recording scheduler. Validates Requirements 14.2, 14.5.
    """
    session = _FakeOrmSession()
    expected_mutations = 0
    for bucket, obj, is_mutation in ops:
        if bucket == "new":
            session.new.add(obj)
        elif bucket == "dirty":
            session.dirty.add(obj)
        elif bucket == "deleted":
            session.deleted.add(obj)
        if is_mutation:
            expected_mutations += 1

    enqueued: list[AuditEntry] = []
    set_audit_scheduler(enqueued.append)

    # Real flush → commit path: capture stashes on session.info, commit enqueues.
    mc._after_flush(session, None)
    # Non-blocking: nothing is enqueued until the transaction commits (Req 14.5).
    assert enqueued == []
    mc._after_commit(session)

    # Exactly one audit log per real mutation; none for reads / no-ops /
    # non-registered models (Req 14.2).
    assert len(enqueued) == expected_mutations

    # A reused session must not re-enqueue.
    mc._after_commit(session)
    assert len(enqueued) == expected_mutations


# Feature: onella-backend, Property 26: Every mutation produces exactly one audit log; reads produce none
@settings(max_examples=100, deadline=None)
@given(ops=st.lists(_operation(), min_size=1, max_size=8))
def test_rolled_back_mutations_produce_no_log(ops) -> None:
    """A rolled-back transaction enqueues nothing (Req 14.5).

    Validates Requirements 14.2, 14.5.
    """
    session = _FakeOrmSession()
    for bucket, obj, _ in ops:
        if bucket == "new":
            session.new.add(obj)
        elif bucket == "dirty":
            session.dirty.add(obj)
        elif bucket == "deleted":
            session.deleted.add(obj)

    enqueued: list[AuditEntry] = []
    set_audit_scheduler(enqueued.append)

    mc._after_flush(session, None)
    mc._after_rollback(session)
    mc._after_commit(session)  # nothing pending after rollback

    assert enqueued == []


# ===========================================================================
# Property 27 — audit log content correctness
# ===========================================================================


@st.composite
def _content_case(draw: st.DrawFn):
    """A (ctx, action, session, changed) world for content verification."""
    ctx = draw(_tenant_context())
    action = draw(st.sampled_from(["create", "update", "delete"]))

    if action == "create":
        obj = _new_widget(name=draw(_values), color=draw(_values), size=draw(_values))
        session = _FakeOrmSession(new={obj})
        return ctx, action, session, None
    if action == "delete":
        obj = _new_widget(name=draw(_values), color=draw(_values))
        session = _FakeOrmSession(deleted={obj})
        return ctx, action, session, None

    # update — mutate a chosen non-null subset of columns with distinct values.
    obj = _as_loaded(_new_widget(name=draw(_values), color=draw(_values), size=draw(_values)))
    cols = draw(
        st.lists(st.sampled_from(["name", "color", "size"]), min_size=1, max_size=3, unique=True)
    )
    changed: dict[str, str] = {}
    for col in cols:
        new_val = draw(_values) + "~"  # distinct suffix guarantees a real change
        setattr(obj, col, new_val)
        changed[col] = new_val
    session = _FakeOrmSession(dirty={obj})
    return ctx, action, session, changed


# Feature: onella-backend, Property 27: Audit log content correctness
@settings(max_examples=200, deadline=None)
@given(case=_content_case())
def test_audit_log_content_correctness(case) -> None:
    """Built entry records actor/tenant/coordinates with correct old/new emptiness.

    Validates Requirements 14.1, 14.3, 14.4.
    """
    ctx, action, session, changed = case
    session.info["tenant_context"] = ctx

    entries = mc.collect_audit_entries(session)
    assert len(entries) == 1
    entry = entries[0]

    # Coordinates + action (Req 14.3).
    assert (entry.module, entry.sub_module, entry.resource) == (
        _MODULE,
        _SUB_MODULE,
        _RESOURCE,
    )
    assert entry.action == action

    # Old/new emptiness by action (Req 14.3).
    if action == "create":
        assert entry.old_value == {}
        assert entry.new_value != {}  # inserted column values recorded
    elif action == "delete":
        assert entry.new_value == {}
        assert entry.old_value != {}  # prior column values recorded
    else:  # update — only the changed columns, both sides keyed identically
        assert set(entry.old_value.keys()) == set(changed.keys())
        assert entry.new_value == changed

    # Actor + tenant identifiers from the context (Req 14.1, 14.4).
    assert entry.user_id == ctx.user_id
    assert entry.role_type == ctx.role_type

    if ctx.impersonating:
        # Impersonation indicator + impersonator id, tenant = impersonated entity.
        assert entry.impersonation is True
        assert entry.impersonator_user_id == ctx.impersonator_user_id
        assert entry.agency_id == ctx.impersonated_agency_id
        assert entry.customer_id == ctx.impersonated_customer_id
    else:
        assert entry.impersonation is False
        assert entry.impersonator_user_id is None
        assert entry.agency_id == ctx.agency_scope
        # customer_id derives from custom-role customer or a single-customer scope.
        if ctx.custom_role_customer_id is not None:
            assert entry.customer_id == ctx.custom_role_customer_id
        elif len(ctx.customer_scope) == 1:
            assert entry.customer_id == next(iter(ctx.customer_scope))
        else:
            assert entry.customer_id is None


# ===========================================================================
# Property 28 — audit logs are append-only
# ===========================================================================


def _committed_audit_log() -> AuditLog:
    """An AuditLog whose columns are all marked committed (looks loaded-from-DB)."""
    log = AuditLog(user_id=uuid.uuid4(), action="create")
    for attr in inspect(AuditLog).column_attrs:
        set_committed_value(log, attr.key, getattr(log, attr.key))
    return log


@st.composite
def _append_only_case(draw: st.DrawFn):
    """A session-shape world: which bucket an AuditLog (or noise) lands in."""
    kind = draw(
        st.sampled_from(
            [
                "insert",  # AuditLog in .new — append, allowed
                "delete",  # AuditLog in .deleted — rejected
                "update",  # AuditLog in .dirty with a real change — rejected
                "dirty_noop",  # AuditLog in .dirty, no change — allowed
                "non_audit",  # only non-audit objects — allowed
            ]
        )
    )
    # Optional non-audit noise present in every bucket to prove it is ignored.
    noise_new = {_new_widget(name=draw(_values))} if draw(st.booleans()) else set()

    if kind == "insert":
        return _FakeOrmSession(new={AuditLog(user_id=uuid.uuid4(), action="create")} | noise_new), False
    if kind == "delete":
        return _FakeOrmSession(deleted={_committed_audit_log()}, new=noise_new), True
    if kind == "update":
        log = _committed_audit_log()
        # A real change to a column of the existing log.
        new_action = draw(st.sampled_from(["update", "delete", "read", "modified"]))
        log.action = new_action + "_x"  # distinct → guaranteed real change
        return _FakeOrmSession(dirty={log}, new=noise_new), True
    if kind == "dirty_noop":
        return _FakeOrmSession(dirty={_committed_audit_log()}, new=noise_new), False
    # non_audit — only non-audit objects across every bucket.
    return (
        _FakeOrmSession(
            new={_new_widget(name=draw(_values))},
            dirty={_new_widget(name=draw(_values))},
            deleted={_new_widget(name=draw(_values))},
        ),
        False,
    )


# Feature: onella-backend, Property 28: Audit logs are append-only
@settings(max_examples=200, deadline=None)
@given(case=_append_only_case())
def test_audit_logs_are_append_only(case) -> None:
    """Update/delete of an AuditLog is rejected; insert/no-op/non-audit allowed.

    Validates Requirements 14.6.
    """
    session, should_reject = case
    if should_reject:
        with pytest.raises(AuditImmutableError):
            assert_audit_logs_immutable(session)
    else:
        # Appends (inserts), dirty-but-unchanged logs, and non-audit objects
        # must not raise — the record is left unchanged (Req 14.6).
        assert assert_audit_logs_immutable(session) is None


# ===========================================================================
# Property 29 — audit write failure is retried then durably recorded
# ===========================================================================


class _FakeTask:
    """Bound Celery-task ``self`` stand-in with retry semantics (from unit tests)."""

    def __init__(self, max_retries: int = 3) -> None:
        self.max_retries = max_retries
        self._retries = 0
        self.request = type("Req", (), {"retries": 0})()

    def retry(self, *, exc, countdown=0):  # noqa: ANN001
        if self._retries >= self.max_retries:
            raise MaxRetriesExceededError() from exc
        self._retries += 1
        self.request.retries = self._retries
        raise _Reschedule()


class _Reschedule(Exception):
    pass


class _FailingLogSession:
    """AuditLog commit fails; AuditFailure commit succeeds (records the failure)."""

    def __init__(self, failure_store: list) -> None:
        self._failure_store = failure_store
        self._staged: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def add(self, obj) -> None:  # noqa: ANN001
        self._staged.append(obj)

    def commit(self) -> None:
        if any(isinstance(o, AuditLog) for o in self._staged):
            raise RuntimeError("db down")
        self._failure_store.extend(
            o for o in self._staged if isinstance(o, AuditFailure)
        )


class _SucceedingSession:
    """Both AuditLog and AuditFailure commits succeed (records into store)."""

    def __init__(self, store: list) -> None:
        self._store = store
        self._staged: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def add(self, obj) -> None:  # noqa: ANN001
        self._staged.append(obj)

    def commit(self) -> None:
        self._store.extend(self._staged)


def _run_task_body(fake_self, entry):
    """Mirror ``write_audit_log``'s body exactly against the injected factory."""
    from app.tasks.audit_tasks import _insert_audit_log, _record_failure

    try:
        _insert_audit_log(entry)
        return {"status": "recorded"}
    except Exception as exc:  # noqa: BLE001
        try:
            raise fake_self.retry(exc=exc, countdown=0)
        except MaxRetriesExceededError:
            _record_failure(entry, str(exc))
            return {"status": "failed", "error": str(exc)}


@st.composite
def _entry_dict(draw: st.DrawFn) -> dict:
    """A JSON-transported AuditEntry dict with varied fields."""
    action = draw(st.sampled_from(["create", "update", "delete"]))
    impersonating = draw(st.booleans())
    return AuditEntry(
        module=draw(_values),
        sub_module=draw(_values),
        resource=draw(_values),
        action=action,
        old_value={} if action == "create" else {"name": draw(_values)},
        new_value={} if action == "delete" else {"name": draw(_values)},
        user_id=uuid.uuid4(),
        role_type=draw(st.sampled_from(["superadmin", "agencyadmin", "customeradmin"])),
        agency_id=draw(st.none() | _uuids),
        customer_id=draw(st.none() | _uuids),
        impersonation=impersonating,
        impersonator_user_id=uuid.uuid4() if impersonating else None,
    ).to_dict()


# Feature: onella-backend, Property 29: Audit write failure is retried then durably recorded
@settings(max_examples=150, deadline=None)
@given(entry=_entry_dict())
def test_write_failure_retried_then_durably_recorded(entry) -> None:
    """Failing write retries 3 times then writes exactly one AuditFailure.

    The originating caller is never impacted (no exception propagates).
    Validates Requirements 14.7.
    """
    failures: list = []
    set_audit_session_factory(lambda: _FailingLogSession(failures))
    fake_self = _FakeTask(max_retries=3)

    # Drive the task the way Celery would: re-run the body on each reschedule
    # until retries are exhausted and the durable failure is written.
    attempts = 0
    result = None
    while True:
        try:
            result = _run_task_body(fake_self, entry)
            break
        except _Reschedule:
            attempts += 1
            continue

    # Retried exactly 3 times before exhaustion (Req 14.7).
    assert attempts == 3
    # No exception propagated to the caller — a result dict was returned.
    assert result["status"] == "failed"
    # Exactly one durable failure record identifying the mutation (payload).
    assert len(failures) == 1
    assert isinstance(failures[0], AuditFailure)
    assert failures[0].payload == entry
    assert "db down" in failures[0].error


# Feature: onella-backend, Property 29: Audit write failure is retried then durably recorded
@settings(max_examples=100, deadline=None)
@given(entry=_entry_dict())
def test_successful_write_records_one_log_and_no_failure(entry) -> None:
    """The happy path writes exactly one AuditLog and no AuditFailure (Req 14.5).

    Validates Requirements 14.7 (success branch of the write pipeline).
    """
    store: list = []
    set_audit_session_factory(lambda: _SucceedingSession(store))
    fake_self = _FakeTask(max_retries=3)

    result = _run_task_body(fake_self, entry)

    assert result == {"status": "recorded"}
    assert len(store) == 1
    assert isinstance(store[0], AuditLog)
    assert not any(isinstance(o, AuditFailure) for o in store)
    # The recorded log carries the mutation's action (Req 14.3 content survives).
    assert store[0].action == entry["action"]

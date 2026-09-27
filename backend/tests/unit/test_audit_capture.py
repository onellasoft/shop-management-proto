"""Unit tests for mutation capture + enqueue-after-commit (Task 21.1, 21.2 — Req 14.1-14.5).

Exercise ``app.audit.mutation_capture`` without a live database or broker:

* create / update / delete on a **registered** model each produce exactly one
  :class:`AuditEntry` with the correct old/new emptiness and the right
  ``module`` / ``sub_module`` / ``resource`` / ``action`` + tenant identifiers
  drawn from a ``session.info`` ``TenantContext`` (Req 14.1, 14.3).
* a read (no flush changes) and a **non-registered** model produce none
  (Req 14.2); ``audit_logs`` is never captured (no recursion).
* impersonation stamps ``impersonation=True`` + the impersonator id (Req 14.4).
* entries are enqueued on ``after_commit`` (not ``after_flush``) and discarded
  on ``after_rollback``; the injected scheduler receives them (Req 14.5).

Capture reads mapped columns via ``inspect`` + per-attribute history, which
work on a mapped instance without an attached session. A throwaway mapped model
(``_Widget``) provides deterministic coordinates; a ``_FakeOrmSession`` supplies
the ``new`` / ``dirty`` / ``deleted`` / ``info`` collections the listeners read.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column

from app.audit import mutation_capture as mc
from app.audit.mutation_capture import (
    AuditEntry,
    collect_audit_entries,
    register_audited_model,
    set_audit_scheduler,
)
from app.core.tenant_context import TenantContext
from app.models.audit import AuditLog


# ---------------------------------------------------------------------------
# Throwaway mapped model registered for auditing
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _Widget(_TestBase):
    __tablename__ = "test_widgets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=True)
    color: Mapped[str] = mapped_column(String, nullable=True)


class _Unregistered(_TestBase):
    __tablename__ = "test_unregistered"

    id: Mapped[str] = mapped_column(String, primary_key=True)


register_audited_model(
    _Widget, module="marketing", sub_module="campaign", resource="widget"
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeOrmSession:
    """Minimal ``Session`` stand-in exposing new/dirty/deleted/info."""

    def __init__(self, *, new=None, dirty=None, deleted=None) -> None:
        self.new = new or set()
        self.dirty = dirty or set()
        self.deleted = deleted or set()
        self.info: dict = {}


def _ctx(**overrides) -> TenantContext:
    base = dict(
        user_id=uuid.uuid4(),
        role_type="agencyadmin",
        agency_scope=uuid.uuid4(),
        customer_scope=frozenset(),
        is_superadmin=False,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )
    base.update(overrides)
    return TenantContext(**base)


def _new_widget(**kwargs) -> _Widget:
    return _Widget(id=str(uuid.uuid4()), **kwargs)


@pytest.fixture(autouse=True)
def _restore_scheduler():
    yield
    set_audit_scheduler(None)


# ===========================================================================
# create / update / delete emptiness + coordinates (Req 14.1, 14.3)
# ===========================================================================


def test_create_produces_entry_with_empty_old_value():
    session = _FakeOrmSession(new={_new_widget(name="Promo", color="red")})
    session.info["tenant_context"] = _ctx()

    entries = collect_audit_entries(session)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "create"
    assert entry.old_value == {}
    assert entry.new_value["name"] == "Promo"
    assert entry.new_value["color"] == "red"
    assert (entry.module, entry.sub_module, entry.resource) == (
        "marketing",
        "campaign",
        "widget",
    )


def test_delete_produces_entry_with_empty_new_value():
    widget = _new_widget(name="Old", color="blue")
    session = _FakeOrmSession(deleted={widget})

    entries = collect_audit_entries(session)

    assert len(entries) == 1
    assert entries[0].action == "delete"
    assert entries[0].new_value == {}
    assert entries[0].old_value["name"] == "Old"


def _as_loaded(widget: _Widget) -> _Widget:
    """Mark every column committed so ``widget`` looks loaded-from-DB (no pending)."""
    from sqlalchemy import inspect
    from sqlalchemy.orm.attributes import set_committed_value

    for attr in inspect(_Widget).column_attrs:
        set_committed_value(widget, attr.key, getattr(widget, attr.key))
    return widget


def test_update_captures_only_changed_columns():
    widget = _as_loaded(_new_widget(name="Before", color="green"))
    widget.name = "After"  # only name changes

    session = _FakeOrmSession(dirty={widget})
    entries = collect_audit_entries(session)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "update"
    assert entry.old_value == {"name": "Before"}
    assert entry.new_value == {"name": "After"}


def test_dirty_without_real_change_produces_no_entry():
    widget = _as_loaded(_new_widget(name="Same"))  # loaded, no pending change
    session = _FakeOrmSession(dirty={widget})

    assert collect_audit_entries(session) == []


# ===========================================================================
# reads / non-registered / recursion guards (Req 14.2)
# ===========================================================================


def test_read_produces_no_entries():
    # A read never populates new/dirty/deleted.
    assert collect_audit_entries(_FakeOrmSession()) == []


def test_non_registered_model_produces_no_entries():
    session = _FakeOrmSession(new={_Unregistered(id="x")})
    assert collect_audit_entries(session) == []


def test_audit_log_itself_is_never_captured():
    log = AuditLog(user_id=uuid.uuid4(), action="create")
    session = _FakeOrmSession(new={log})
    assert collect_audit_entries(session) == []


def test_registering_audit_log_is_refused():
    with pytest.raises(ValueError):
        register_audited_model(
            AuditLog, module="m", sub_module="s", resource="r"
        )


# ===========================================================================
# tenant identifiers + impersonation (Req 14.1, 14.4)
# ===========================================================================


def test_entry_carries_tenant_identifiers_from_context():
    agency = uuid.uuid4()
    customer = uuid.uuid4()
    user = uuid.uuid4()
    ctx = _ctx(
        user_id=user,
        role_type="customeradmin",
        agency_scope=agency,
        customer_scope=frozenset({customer}),
    )
    session = _FakeOrmSession(new={_new_widget(name="X")})
    session.info["tenant_context"] = ctx

    entry = collect_audit_entries(session)[0]

    assert entry.user_id == user
    assert entry.role_type == "customeradmin"
    assert entry.agency_id == agency
    assert entry.customer_id == customer
    assert entry.impersonation is False
    assert entry.impersonator_user_id is None


def test_impersonation_stamps_flag_and_impersonator(monkeypatch):
    impersonator = uuid.uuid4()
    imp_agency = uuid.uuid4()
    imp_customer = uuid.uuid4()
    ctx = _ctx(
        impersonating=True,
        impersonated_agency_id=imp_agency,
        impersonated_customer_id=imp_customer,
        impersonator_user_id=impersonator,
    )
    session = _FakeOrmSession(new={_new_widget(name="X")})
    session.info["tenant_context"] = ctx

    entry = collect_audit_entries(session)[0]

    assert entry.impersonation is True
    assert entry.impersonator_user_id == impersonator
    assert entry.agency_id == imp_agency
    assert entry.customer_id == imp_customer


def test_no_context_session_does_not_crash():
    session = _FakeOrmSession(new={_new_widget(name="X")})
    entry = collect_audit_entries(session)[0]
    assert entry.user_id is None
    assert entry.role_type is None


# ===========================================================================
# enqueue on commit / discard on rollback (Req 14.5)
# ===========================================================================


def test_after_flush_records_and_after_commit_enqueues():
    session = _FakeOrmSession(new={_new_widget(name="X")})
    session.info["tenant_context"] = _ctx()
    enqueued: list[AuditEntry] = []
    set_audit_scheduler(enqueued.append)

    mc._after_flush(session, None)
    assert session.info[mc._PENDING_ENTRIES_KEY]  # stashed, not yet enqueued
    assert enqueued == []

    mc._after_commit(session)
    assert len(enqueued) == 1
    assert mc._PENDING_ENTRIES_KEY not in session.info


def test_after_flush_accumulates_across_flushes():
    session = _FakeOrmSession(new={_new_widget(name="A")})
    mc._after_flush(session, None)
    session.new = {_new_widget(name="B")}
    mc._after_flush(session, None)

    assert len(session.info[mc._PENDING_ENTRIES_KEY]) == 2


def test_after_rollback_discards_pending_entries():
    session = _FakeOrmSession(new={_new_widget(name="X")})
    mc._after_flush(session, None)
    assert mc._PENDING_ENTRIES_KEY in session.info

    enqueued: list[AuditEntry] = []
    set_audit_scheduler(enqueued.append)
    mc._after_rollback(session)
    mc._after_commit(session)  # nothing left to enqueue

    assert mc._PENDING_ENTRIES_KEY not in session.info
    assert enqueued == []


def test_to_dict_is_json_safe():
    entry = AuditEntry(
        module="m",
        sub_module="s",
        resource="r",
        action="create",
        old_value={},
        new_value={"name": "X"},
        user_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
    )
    payload = entry.to_dict()
    assert isinstance(payload["user_id"], str)
    assert isinstance(payload["agency_id"], str)
    assert payload["customer_id"] is None
    assert payload["action"] == "create"

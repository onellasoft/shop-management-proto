"""Unit tests for the append-only service-layer guard (Task 21.3 — Req 14.6).

``assert_audit_logs_immutable`` (fired from ``before_flush``) must reject any
attempt to UPDATE or DELETE an :class:`~app.models.audit.AuditLog` by raising
:class:`~app.core.errors.AuditImmutableError`, while leaving INSERTs (appends)
untouched. Exercised against a ``_FakeOrmSession`` so no live database is
needed; update detection uses real per-attribute history on a mapped instance.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.audit.mutation_capture import assert_audit_logs_immutable
from app.core.errors import AuditImmutableError
from app.models.audit import AuditLog


class _FakeOrmSession:
    def __init__(self, *, new=None, dirty=None, deleted=None) -> None:
        self.new = new or set()
        self.dirty = dirty or set()
        self.deleted = deleted or set()
        self.info: dict = {}


def _audit_log() -> AuditLog:
    return AuditLog(user_id=uuid.uuid4(), action="create")


def test_insert_of_audit_log_is_allowed():
    session = _FakeOrmSession(new={_audit_log()})
    # Appends must not raise (Req 14.6 permits inserts).
    assert assert_audit_logs_immutable(session) is None


def test_delete_of_audit_log_raises():
    session = _FakeOrmSession(deleted={_audit_log()})
    with pytest.raises(AuditImmutableError):
        assert_audit_logs_immutable(session)


def test_update_of_audit_log_raises():
    log = _audit_log()
    set_committed_value(log, "action", "create")
    log.action = "update"  # a real change
    session = _FakeOrmSession(dirty={log})

    with pytest.raises(AuditImmutableError):
        assert_audit_logs_immutable(session)


def test_dirty_audit_log_without_change_does_not_raise():
    from sqlalchemy import inspect

    log = _audit_log()
    # Mark every column committed so the instance looks loaded-from-DB with no
    # pending change (a dirty-but-unmodified AuditLog must not be rejected).
    for attr in inspect(AuditLog).column_attrs:
        set_committed_value(log, attr.key, getattr(log, attr.key))
    session = _FakeOrmSession(dirty={log})

    assert assert_audit_logs_immutable(session) is None


def test_non_audit_objects_are_ignored():
    session = _FakeOrmSession(new={object()}, dirty={object()}, deleted={object()})
    assert assert_audit_logs_immutable(session) is None

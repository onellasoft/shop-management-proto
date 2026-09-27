"""Unit tests for the async audit write task (Task 21.2 — Req 14.5, 14.7).

Exercise the write path in ``app.tasks.audit_tasks`` against an in-memory fake
session (no live Celery broker or database):

* a successful INSERT records one :class:`~app.models.audit.AuditLog`
  (Req 14.5).
* repeated INSERT failure retries up to 3 times and, once exhausted, records a
  durable :class:`~app.models.audit.AuditFailure` carrying the payload + error
  without raising back to the caller (Req 14.7).
* ``AuditService.enqueue`` dispatches the Celery task with the serialized entry.

The Celery task is bound, so its body is driven with a fake ``self`` providing
``request.retries`` and a ``retry()`` that mimics Celery — re-raising while
retries remain and raising ``MaxRetriesExceededError`` once exhausted.
"""

from __future__ import annotations

import uuid

import pytest
from celery.exceptions import MaxRetriesExceededError

from app.audit.mutation_capture import AuditEntry
from app.models.audit import AuditFailure, AuditLog
from app.tasks import audit_tasks
from app.tasks.audit_tasks import set_audit_session_factory


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSession:
    """Context-managed session recording added rows; INSERT may be forced to fail."""

    def __init__(self, store: list, *, fail: bool) -> None:
        self._store = store
        self._fail = fail
        self._staged: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def add(self, obj) -> None:
        self._staged.append(obj)

    def commit(self) -> None:
        if self._fail:
            raise RuntimeError("db down")
        self._store.extend(self._staged)


def _factory(store: list, *, fail: bool):
    return lambda: _FakeSession(store, fail=fail)


class _FakeTask:
    """Stand-in for the bound Celery task ``self`` with retry semantics."""

    def __init__(self, max_retries: int = 3) -> None:
        self.max_retries = max_retries
        self._retries = 0
        self.request = type("Req", (), {"retries": 0})()

    def retry(self, *, exc, countdown=0):  # noqa: ANN001
        if self._retries >= self.max_retries:
            raise MaxRetriesExceededError() from exc
        self._retries += 1
        self.request.retries = self._retries
        # Real Celery re-raises to reschedule; the task body wraps retry() in a
        # raise, so re-invoke the body to emulate the next attempt.
        raise _Reschedule()


class _Reschedule(Exception):
    pass


def _entry_dict() -> dict:
    return AuditEntry(
        module="marketing",
        sub_module="campaign",
        resource="widget",
        action="create",
        old_value={},
        new_value={"name": "X"},
        user_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
    ).to_dict()


@pytest.fixture(autouse=True)
def _restore_factory():
    yield
    set_audit_session_factory(None)


# ===========================================================================
# happy path (Req 14.5)
# ===========================================================================


def test_successful_write_inserts_one_audit_log():
    store: list = []
    set_audit_session_factory(_factory(store, fail=False))

    result = audit_tasks._insert_audit_log(_entry_dict())

    assert result is None
    assert len(store) == 1
    assert isinstance(store[0], AuditLog)
    assert store[0].action == "create"
    assert store[0].new_value == {"name": "X"}


def test_audit_log_from_entry_parses_uuids_and_impersonation():
    user = uuid.uuid4()
    impersonator = uuid.uuid4()
    entry = AuditEntry(
        module="m",
        sub_module="s",
        resource="r",
        action="delete",
        old_value={"a": 1},
        new_value={},
        user_id=user,
        impersonation=True,
        impersonator_user_id=impersonator,
    ).to_dict()

    log = audit_tasks._audit_log_from_entry(entry)

    assert log.user_id == user
    assert log.impersonation is True
    assert log.impersonator_user_id == impersonator
    assert log.new_value == {}


# ===========================================================================
# retry then durable failure (Req 14.7)
# ===========================================================================


def test_retries_three_times_then_records_audit_failure():
    entry = _entry_dict()
    failures: list = []
    log_store: list = []

    def factory():
        # AuditLog insert fails; AuditFailure insert succeeds.
        return _FailingThenFailureSession(log_store, failures)

    set_audit_session_factory(factory)

    fake_self = _FakeTask(max_retries=3)

    # Drive the task body the way Celery would: re-run on each reschedule until
    # retries are exhausted and the failure record is written.
    attempts = 0
    result = None
    while True:
        try:
            result = _run_task_body(fake_self, entry)
            break
        except _Reschedule:
            attempts += 1
            continue

    assert attempts == 3  # retried 3 times before exhaustion
    assert result["status"] == "failed"
    assert len(failures) == 1
    assert isinstance(failures[0], AuditFailure)
    assert failures[0].payload == entry
    assert "db down" in failures[0].error


class _FailingThenFailureSession:
    """Session whose AuditLog commit fails but AuditFailure commit succeeds."""

    def __init__(self, log_store: list, failure_store: list) -> None:
        self._log_store = log_store
        self._failure_store = failure_store
        self._staged: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def add(self, obj) -> None:
        self._staged.append(obj)

    def commit(self) -> None:
        if any(isinstance(o, AuditLog) for o in self._staged):
            raise RuntimeError("db down")
        self._failure_store.extend(
            o for o in self._staged if isinstance(o, AuditFailure)
        )


def _run_task_body(fake_self, entry):
    """Invoke the pure task body (mirrors write_audit_log's implementation)."""
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


# ===========================================================================
# enqueue (Req 14.5)
# ===========================================================================


def test_enqueue_dispatches_serialized_entry(monkeypatch):
    from app.services.audit_service import AuditService

    captured: list = []

    class _FakeDelay:
        def delay(self, payload):  # noqa: ANN001
            captured.append(payload)

    monkeypatch.setattr(audit_tasks, "write_audit_log", _FakeDelay())

    entry = AuditEntry(
        module="m",
        sub_module="s",
        resource="r",
        action="create",
        old_value={},
        new_value={},
    )
    AuditService().enqueue(entry)

    assert len(captured) == 1
    assert captured[0]["module"] == "m"
    assert captured[0]["action"] == "create"

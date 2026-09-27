"""SQLAlchemy-driven mutation capture and append-only enforcement (Req 14).

This module implements three cooperating pieces of the audit subsystem, all
attached as SQLAlchemy ``Session`` event listeners so they observe *every*
mutation regardless of which service performed it:

* **Mutation capture with old/new diffing** (Task 21.1 — Req 14.1-14.4).
  ``after_flush`` inspects the flush for inserts (``session.new``), updates
  (``session.dirty`` with per-attribute history), and deletes
  (``session.deleted``) of *audited* models and builds one :class:`AuditEntry`
  per mutated instance:

  * **create** → ``old_value = {}``, ``new_value =`` inserted column values.
  * **update** → ``old_value =`` changed columns' prior values,
    ``new_value =`` changed columns' new values.
  * **delete** → ``old_value =`` the row's column values, ``new_value = {}``.

  Reads never flush changes, so reads are never captured (Req 14.2). The
  captured entry carries the acting :class:`~app.core.tenant_context.TenantContext`
  identifiers (``user_id``, ``role_type``, ``agency_id``, ``customer_id``) and,
  while impersonating, ``impersonation=True`` + ``impersonator_user_id``
  (Req 14.1, 14.3, 14.4).

* **Enqueue after commit** (Task 21.2 — Req 14.5). The entries built at flush
  time are stashed on ``session.info`` and only handed to the async writer in
  ``after_commit`` — after the originating transaction is durable — via an
  injectable scheduler seam (:func:`set_audit_scheduler`). ``after_rollback``
  discards them so a rolled-back mutation is never logged. This mirrors the
  established post-commit pattern in
  ``app.cache.customer_cache_invalidation``.

* **Append-only guard** (Task 21.3 — Req 14.6). ``before_flush`` rejects any
  attempt to UPDATE or DELETE an :class:`~app.models.audit.AuditLog` by raising
  :class:`~app.core.errors.AuditImmutableError`, complementing the DB trigger
  from Task 20.2. INSERTs (appends) are allowed.

Which models are audited (the registry)
----------------------------------------
Auditing is **opt-in and explicit** — we deliberately do *not* try to map every
ORM model onto a permission-graph action. A model participates only when it has
declared its permission-graph coordinates ``(module, sub_module, resource)``,
either by setting the class attribute ``__audit_resource__`` or by calling
:func:`register_audited_model`. The ``action`` (``create`` / ``update`` /
``delete``) is derived from the SQLAlchemy operation. Models without an opt-in
are never audited, which keeps infrastructure tables (refresh tokens, the
``audit_logs`` / ``audit_failures`` tables themselves, etc.) out of the log and
prevents recursion — capturing an audit write as an audited mutation.

Making the acting context available during flush
-------------------------------------------------
The event hooks run inside the DB session and have no natural access to the
request's ``TenantContext``. The request layer stashes it on the session with
:func:`set_session_tenant_context` (``session.info["tenant_context"] = ctx``);
the flush hook reads it from there. When absent (a system/no-context session),
capture still runs and records what it can (``user_id`` / ``role_type`` may be
``None``) rather than crashing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, attributes

from app.core.errors import AuditImmutableError
from app.models.audit import AuditFailure, AuditLog

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.core.tenant_context import TenantContext

# ``session.info`` keys — the seam between flush-time capture and commit-time
# enqueue, mirroring ``customer_cache_invalidation``'s single-key stash.
_TENANT_CONTEXT_KEY = "tenant_context"
_PENDING_ENTRIES_KEY = "_audit_pending_entries"

# Tables that must never be audited even if (mis)registered — capturing an
# audit write as an audited mutation would recurse. Belt-and-suspenders on top
# of the opt-in registry.
_NEVER_AUDITED_TABLES = frozenset({AuditLog.__tablename__, AuditFailure.__tablename__})


# ---------------------------------------------------------------------------
# AuditEntry — the captured, JSON-serializable mutation record
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    """A captured mutation, ready to enqueue for the async writer (Req 14.1-14.4).

    Field names mirror :class:`~app.models.audit.AuditLog` columns so the
    Celery task can build the row directly from :meth:`to_dict`.
    """

    module: str | None
    sub_module: str | None
    resource: str | None
    action: str
    old_value: dict[str, Any]
    new_value: dict[str, Any]
    user_id: uuid.UUID | None = None
    role_type: str | None = None
    agency_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    impersonation: bool = False
    impersonator_user_id: uuid.UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict for Celery transport (json serializer).

        UUIDs are stringified so the entry survives the JSON broker; the write
        task re-parses them when building the :class:`AuditLog`.
        """

        def _str(value: Any) -> Any:  # noqa: ANN401
            return str(value) if value is not None else None

        return {
            "module": self.module,
            "sub_module": self.sub_module,
            "resource": self.resource,
            "action": self.action,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "user_id": _str(self.user_id),
            "role_type": self.role_type,
            "agency_id": _str(self.agency_id),
            "customer_id": _str(self.customer_id),
            "impersonation": self.impersonation,
            "impersonator_user_id": _str(self.impersonator_user_id),
        }


# ---------------------------------------------------------------------------
# Audited-model registry (explicit opt-in)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AuditCoordinates:
    """Permission-graph coordinates a model opts into for auditing."""

    module: str
    sub_module: str
    resource: str


# Maps an ORM model class → its permission-graph coordinates. Populated by
# ``register_audited_model`` and by ``__audit_resource__`` discovery.
_AUDITED_MODELS: dict[type, _AuditCoordinates] = {}


def register_audited_model(
    model: type,
    *,
    module: str,
    sub_module: str,
    resource: str,
) -> None:
    """Opt ``model`` into mutation auditing under the given coordinates (Req 14.3).

    The ``(module, sub_module, resource)`` triple is the permission-graph
    address recorded on every :class:`AuditLog` for this model; the ``action``
    is derived per-operation. Registering the ``audit_logs`` /
    ``audit_failures`` tables is refused to guarantee the log can never audit
    itself.
    """
    table = getattr(model, "__tablename__", None)
    if table in _NEVER_AUDITED_TABLES:
        raise ValueError(f"{table!r} is an audit infrastructure table and cannot be audited")
    _AUDITED_MODELS[model] = _AuditCoordinates(
        module=module, sub_module=sub_module, resource=resource
    )


def _coordinates_for(instance: object) -> _AuditCoordinates | None:
    """Return the audit coordinates for ``instance``'s model, or ``None``.

    Resolves an explicit :func:`register_audited_model` entry first, then falls
    back to a class-level ``__audit_resource__ = (module, sub_module, resource)``
    declaration (lazily registering it so later lookups are cheap). Anything
    that lands on a never-audited table is excluded regardless.
    """
    model = type(instance)
    if getattr(model, "__tablename__", None) in _NEVER_AUDITED_TABLES:
        return None

    coords = _AUDITED_MODELS.get(model)
    if coords is not None:
        return coords

    declared = getattr(model, "__audit_resource__", None)
    if declared is not None:
        module, sub_module, resource = declared
        coords = _AuditCoordinates(
            module=module, sub_module=sub_module, resource=resource
        )
        _AUDITED_MODELS[model] = coords
        return coords

    return None


# ---------------------------------------------------------------------------
# Column-value / diff helpers
# ---------------------------------------------------------------------------


def _json_safe(value: Any) -> Any:  # noqa: ANN401
    """Coerce a column value into something JSON-serializable for the diff."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _column_keys(instance: object) -> list[str]:
    """Return the mapped column attribute names for ``instance``'s model."""
    mapper = inspect(type(instance))
    return [attr.key for attr in mapper.column_attrs]


def _column_values(instance: object) -> dict[str, Any]:
    """Snapshot every mapped column of ``instance`` as a JSON-safe dict."""
    return {key: _json_safe(getattr(instance, key)) for key in _column_keys(instance)}


def _changed_columns(instance: object) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(old, new)`` dicts of the columns that changed in this flush.

    Uses per-attribute history so an instance flagged dirty for reasons other
    than a real value change (e.g. a same-value set) yields empty diffs and is
    treated as no-op by the caller.
    """
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    for key in _column_keys(instance):
        history = attributes.get_history(instance, key)
        if not history.has_changes():
            continue
        # ``deleted`` holds prior value(s); ``added`` holds the new value(s).
        if history.deleted:
            old[key] = _json_safe(history.deleted[0])
        else:
            old[key] = None
        if history.added:
            new[key] = _json_safe(history.added[0])
        else:
            new[key] = None
    return old, new


# ---------------------------------------------------------------------------
# Context stashing (request layer → flush hook)
# ---------------------------------------------------------------------------


def set_session_tenant_context(session: Session, ctx: TenantContext | None) -> None:
    """Stash the acting ``TenantContext`` on ``session.info`` for flush capture.

    The request layer calls this once the context is derived so the flush hook
    (which has no request access) can attribute captured mutations to the actor
    (Req 14.1, 14.4). Passing ``None`` clears it.
    """
    if ctx is None:
        session.info.pop(_TENANT_CONTEXT_KEY, None)
    else:
        session.info[_TENANT_CONTEXT_KEY] = ctx


def _context_from_session(session: Session) -> TenantContext | None:
    """Read the acting context stashed on ``session.info`` (may be absent)."""
    return session.info.get(_TENANT_CONTEXT_KEY)


def _apply_context(entry: AuditEntry, ctx: TenantContext | None) -> None:
    """Populate ``entry``'s actor/tenant fields from ``ctx`` (Req 14.1, 14.4).

    A no-context session (``ctx is None``) leaves the identity fields ``None``
    rather than crashing — capture is best-effort for system sessions.
    """
    if ctx is None:
        return
    entry.user_id = ctx.user_id
    entry.role_type = ctx.role_type
    # Under impersonation the enforced scope is the impersonated entity
    # (Req 12.1), so the tenant identifiers reflect that entity.
    if ctx.impersonating:
        entry.agency_id = ctx.impersonated_agency_id
        entry.customer_id = ctx.impersonated_customer_id
        entry.impersonation = True
        entry.impersonator_user_id = ctx.impersonator_user_id
    else:
        entry.agency_id = ctx.agency_scope
        # customer_scope is a (possibly multi) set; a single-customer context
        # records that customer, otherwise leave it unset.
        if ctx.custom_role_customer_id is not None:
            entry.customer_id = ctx.custom_role_customer_id
        elif len(ctx.customer_scope) == 1:
            entry.customer_id = next(iter(ctx.customer_scope))


# ---------------------------------------------------------------------------
# Flush-time capture (build AuditEntry per audited mutation)
# ---------------------------------------------------------------------------


def collect_audit_entries(session: Session) -> list[AuditEntry]:
    """Build one :class:`AuditEntry` per audited mutation in ``session``'s flush.

    * inserts (``session.new``) → create entries (empty ``old_value``).
    * deletes (``session.deleted``) → delete entries (empty ``new_value``).
    * updates (``session.dirty`` with changed columns) → update entries.

    Non-registered models, and any dirty instance whose columns did not
    actually change, produce nothing (Req 14.2 — reads never reach here).
    """
    ctx = _context_from_session(session)
    entries: list[AuditEntry] = []

    for obj in session.new:
        coords = _coordinates_for(obj)
        if coords is None:
            continue
        entry = AuditEntry(
            module=coords.module,
            sub_module=coords.sub_module,
            resource=coords.resource,
            action="create",
            old_value={},
            new_value=_column_values(obj),
        )
        _apply_context(entry, ctx)
        entries.append(entry)

    for obj in session.deleted:
        coords = _coordinates_for(obj)
        if coords is None:
            continue
        entry = AuditEntry(
            module=coords.module,
            sub_module=coords.sub_module,
            resource=coords.resource,
            action="delete",
            old_value=_column_values(obj),
            new_value={},
        )
        _apply_context(entry, ctx)
        entries.append(entry)

    for obj in session.dirty:
        coords = _coordinates_for(obj)
        if coords is None:
            continue
        old, new = _changed_columns(obj)
        if not old and not new:
            continue  # dirty but nothing actually changed → not a mutation
        entry = AuditEntry(
            module=coords.module,
            sub_module=coords.sub_module,
            resource=coords.resource,
            action="update",
            old_value=old,
            new_value=new,
        )
        _apply_context(entry, ctx)
        entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Append-only guard (Req 14.6)
# ---------------------------------------------------------------------------


def assert_audit_logs_immutable(session: Session) -> None:
    """Raise :class:`AuditImmutableError` if this flush updates/deletes an AuditLog.

    Complements the DB trigger (Task 20.2) so the immutability is caught at the
    application layer across every mutation path. INSERTs (appends) are allowed
    — only ``session.dirty`` (with real changes) and ``session.deleted`` are
    rejected (Req 14.6).
    """
    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            raise AuditImmutableError()
    for obj in session.dirty:
        if isinstance(obj, AuditLog):
            old, new = _changed_columns(obj)
            if old or new:
                raise AuditImmutableError()


# ---------------------------------------------------------------------------
# Post-commit enqueue scheduler (injectable seam)
# ---------------------------------------------------------------------------

#: Signature of the scheduler that dispatches a captured entry to the writer.
Scheduler = Callable[[AuditEntry], None]


def _default_scheduler(entry: AuditEntry) -> None:
    """Enqueue ``entry`` onto the Celery audit write task (non-blocking, Req 14.5).

    Imported lazily so importing this module never forces the Celery app /
    broker configuration to load (tests inject a recorder instead).
    """
    from app.services.audit_service import get_audit_service

    get_audit_service().enqueue(entry)


_scheduler: Scheduler = _default_scheduler


def set_audit_scheduler(scheduler: Scheduler | None) -> None:
    """Override the post-commit enqueue scheduler (mainly for tests).

    Passing ``None`` restores the default Celery-backed scheduler. Tests inject
    a synchronous recorder to capture enqueued entries without a live broker.
    """
    global _scheduler
    _scheduler = scheduler if scheduler is not None else _default_scheduler


# ---------------------------------------------------------------------------
# SQLAlchemy event listeners
# ---------------------------------------------------------------------------


def _before_flush(session: Session, _flush_context: Any, _instances: Any) -> None:  # noqa: ANN401
    """Reject AuditLog update/delete before the flush touches the DB (Req 14.6)."""
    assert_audit_logs_immutable(session)


def _after_flush(session: Session, _flush_context: Any) -> None:  # noqa: ANN401
    """Capture audited mutations and stash the entries on ``session.info``.

    Accumulates across multiple flushes in one transaction so the eventual
    commit enqueues every captured mutation, not just the last flush's.
    """
    captured = collect_audit_entries(session)
    if not captured:
        return
    pending: list[AuditEntry] = session.info.setdefault(_PENDING_ENTRIES_KEY, [])
    pending.extend(captured)


def _after_commit(session: Session) -> None:
    """Enqueue the captured entries once the transaction is durable (Req 14.5).

    Enqueue happens here (not at flush) so a mutation is logged only if it
    truly committed, and it is non-blocking — the scheduler hands each entry to
    Celery. The pending list is cleared so a reused session does not re-enqueue.
    """
    pending = session.info.pop(_PENDING_ENTRIES_KEY, None)
    if not pending:
        return
    for entry in pending:
        _scheduler(entry)


def _after_rollback(session: Session) -> None:
    """Discard captured entries for a rolled-back transaction (Req 14.5).

    A rolled-back mutation never became durable, so it must not be logged.
    """
    session.info.pop(_PENDING_ENTRIES_KEY, None)


def register_audit_listeners(target: Any = Session) -> None:  # noqa: ANN401
    """Register the flush/commit/rollback listeners on ``target`` (idempotent).

    ``target`` defaults to the :class:`~sqlalchemy.orm.Session` class so every
    session (including the async engine's underlying sync session) participates.
    Guarded so repeated calls (re-imports in tests) do not attach duplicates.
    Coexists with ``register_customer_cache_invalidation`` on the same class.
    """
    if not event.contains(target, "before_flush", _before_flush):
        event.listen(target, "before_flush", _before_flush)
    if not event.contains(target, "after_flush", _after_flush):
        event.listen(target, "after_flush", _after_flush)
    if not event.contains(target, "after_commit", _after_commit):
        event.listen(target, "after_commit", _after_commit)
    if not event.contains(target, "after_rollback", _after_rollback):
        event.listen(target, "after_rollback", _after_rollback)


__all__ = [
    "AuditEntry",
    "assert_audit_logs_immutable",
    "collect_audit_entries",
    "register_audit_listeners",
    "register_audited_model",
    "set_audit_scheduler",
    "set_session_tenant_context",
    "Scheduler",
]

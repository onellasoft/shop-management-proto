"""Agency customer-list cache invalidation on Customer lifecycle changes.

Task 15.2 — Requirement 10.4, 10.5. When a Customer is **added to**, **removed
from**, **suspended within**, or **activated within** an Agency, the cached
accessible-customer list for that Agency (``agency:{id}:customers``, Task 15.1)
must be deleted within 5 seconds of the change being committed (Req 10.4), so
the next resolution repopulates from the database (Req 10.5).

Design reference — "Agency Customer-List Redis Cache (Req 10)":

    Invalidation: on customer add/remove/suspend/activate, delete the key
    within 5 s of commit ... a post-commit hook guarantees the delete. Next
    request repopulates from DB.

Two integration points are provided; both funnel into the same async
invalidation primitive (:class:`~app.cache.customer_list_cache.AgencyCustomerListCache.invalidate`,
also surfaced as ``AuthorizationService.invalidate_agency_customer_cache``):

1. **Automatic ORM post-commit hook** (primary). SQLAlchemy event listeners
   observe every session:

   * ``after_flush`` — :func:`collect_affected_agency_ids` inspects the flush
     for new Customers, deleted Customers, and Customers whose ``status``
     changed (add / remove / suspend / activate) and records the affected
     ``agency_id`` values on ``session.info``. Detection must happen at flush
     time because ``after_commit`` no longer has access to the dirty/deleted
     collections or attribute history.
   * ``after_commit`` — :func:`_after_commit` reads the recorded agency ids
     (now that the change is durable) and schedules the async delete of each
     agency's cache key. Because ``after_commit`` is a synchronous callback,
     the async invalidation is dispatched onto the running event loop via the
     injectable :data:`_scheduler` (see :func:`set_cache_invalidation_scheduler`);
     tests inject a synchronous recorder instead of a live loop/Redis.

   Register the listeners once at startup with
   :func:`register_customer_cache_invalidation` (wired from
   :func:`app.db.session` import side-effects / the app factory).

2. **Explicit lifecycle helpers** (for call sites). The eventual Customer
   CRUD/lifecycle endpoints (a later task — no dedicated customer endpoints
   exist yet) may call :func:`on_customer_added`, :func:`on_customer_removed`,
   :func:`on_customer_suspended`, or :func:`on_customer_activated` right after
   committing the change. These are thin wrappers over
   :func:`invalidate_agency_customer_cache` that make the intent explicit at the
   mutation site and are independent of the ORM hook.

Both mechanisms satisfy the 5-second bound because they run in the same request
immediately after the commit is durable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session, attributes

from app.cache.customer_list_cache import (
    AgencyCustomerListCache,
    get_agency_customer_list_cache,
)
from app.models.customer import Customer

# Key under which the affected agency ids are stashed on ``session.info``
# between ``after_flush`` (detection) and ``after_commit`` (dispatch).
_SESSION_INFO_KEY = "_agency_customer_cache_invalidations"

# ---------------------------------------------------------------------------
# Invalidation primitive
# ---------------------------------------------------------------------------


async def invalidate_agency_customer_cache(
    agency_id: UUID,
    *,
    cache: AgencyCustomerListCache | None = None,
) -> None:
    """Delete the cached accessible-customer list for ``agency_id`` (Req 10.4, 10.5).

    The single async primitive every lifecycle path funnels through. Deletes
    the ``agency:{agency_id}:customers`` key so the next resolution reloads
    from the database (Req 10.5). ``cache`` defaults to the shared
    Redis-backed cache; tests inject an in-memory fake.
    """
    active = cache if cache is not None else get_agency_customer_list_cache()
    await active.invalidate(agency_id)


# ---------------------------------------------------------------------------
# Explicit lifecycle helpers (call from Customer lifecycle operations)
# ---------------------------------------------------------------------------


async def on_customer_added(
    agency_id: UUID, *, cache: AgencyCustomerListCache | None = None
) -> None:
    """Invalidate the Agency's cached list after a Customer is added (Req 10.4)."""
    await invalidate_agency_customer_cache(agency_id, cache=cache)


async def on_customer_removed(
    agency_id: UUID, *, cache: AgencyCustomerListCache | None = None
) -> None:
    """Invalidate the Agency's cached list after a Customer is removed (Req 10.4)."""
    await invalidate_agency_customer_cache(agency_id, cache=cache)


async def on_customer_suspended(
    agency_id: UUID, *, cache: AgencyCustomerListCache | None = None
) -> None:
    """Invalidate the Agency's cached list after a Customer is suspended (Req 10.4)."""
    await invalidate_agency_customer_cache(agency_id, cache=cache)


async def on_customer_activated(
    agency_id: UUID, *, cache: AgencyCustomerListCache | None = None
) -> None:
    """Invalidate the Agency's cached list after a Customer is activated (Req 10.4)."""
    await invalidate_agency_customer_cache(agency_id, cache=cache)


# ---------------------------------------------------------------------------
# Flush-time detection (add / remove / suspend / activate)
# ---------------------------------------------------------------------------


def _status_changed(customer: Customer) -> bool:
    """Return whether ``customer``'s ``status`` was modified in this flush.

    Suspend and activate are ``status`` transitions (``active`` ↔ ``suspended``)
    on an existing row. The attribute's history has changes only when the value
    was actually set to something different, so an untouched Customer in
    ``session.dirty`` (e.g. a ``name`` edit) does not trigger invalidation.
    """
    history = attributes.get_history(customer, "status")
    return history.has_changes()


def collect_affected_agency_ids(session: Session) -> set[UUID]:
    """Return the ``agency_id`` of every Customer changed in ``session``'s flush.

    Detects the four lifecycle events of Req 10.4:

    * **add** — a ``Customer`` in ``session.new`` (insert).
    * **remove** — a ``Customer`` in ``session.deleted`` (delete).
    * **suspend / activate** — a ``Customer`` in ``session.dirty`` whose
      ``status`` attribute changed in this flush.

    A ``Customer`` whose non-``status`` fields changed does not affect the
    accessible-customer *list* (membership/visibility), so it is excluded to
    avoid needless cache churn.

    Called from ``after_flush`` because ``session.new`` / ``deleted`` /
    ``dirty`` and per-attribute history are only meaningful before the
    transaction commits.
    """
    affected: set[UUID] = set()

    for obj in session.new:
        if isinstance(obj, Customer) and obj.agency_id is not None:
            affected.add(obj.agency_id)

    for obj in session.deleted:
        if isinstance(obj, Customer) and obj.agency_id is not None:
            affected.add(obj.agency_id)

    for obj in session.dirty:
        if (
            isinstance(obj, Customer)
            and obj.agency_id is not None
            and _status_changed(obj)
        ):
            affected.add(obj.agency_id)

    return affected


# ---------------------------------------------------------------------------
# Post-commit dispatch scheduler (injectable seam)
# ---------------------------------------------------------------------------

#: Signature of the scheduler that dispatches the async invalidation coroutine.
Scheduler = Callable[[Awaitable[None]], None]


def _default_scheduler(coro: Awaitable[None]) -> None:
    """Dispatch ``coro`` onto the running event loop without blocking.

    ``after_commit`` fires synchronously inside the same task that awaited the
    ``AsyncSession`` commit, so a running loop is available; the invalidation
    is scheduled as a fire-and-forget task that completes well within the 5s
    bound (Req 10.4). If no loop is running (e.g. a synchronous session used
    outside the async app), the coroutine is run to completion instead so the
    delete is not silently dropped.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)  # type: ignore[arg-type]
        return
    loop.create_task(coro)  # type: ignore[arg-type]


_scheduler: Scheduler = _default_scheduler


def set_cache_invalidation_scheduler(scheduler: Scheduler | None) -> None:
    """Override the post-commit dispatch scheduler (mainly for tests).

    Passing ``None`` restores the default event-loop scheduler. Tests inject a
    synchronous recorder so they can assert which agencies were invalidated
    without a live event loop or Redis.
    """
    global _scheduler
    _scheduler = scheduler if scheduler is not None else _default_scheduler


def _dispatch_invalidations(
    agency_ids: Iterable[UUID],
    *,
    cache: AgencyCustomerListCache | None = None,
) -> None:
    """Schedule the async cache delete for each affected agency id."""
    for agency_id in agency_ids:
        _scheduler(invalidate_agency_customer_cache(agency_id, cache=cache))


# ---------------------------------------------------------------------------
# SQLAlchemy event listeners
# ---------------------------------------------------------------------------


def _after_flush(session: Session, _flush_context: Any) -> None:  # noqa: ANN401
    """Record the agencies affected by this flush on ``session.info``.

    Accumulates across multiple flushes within a single transaction so a
    subsequent commit invalidates every agency touched, not just the last
    flush's.
    """
    affected = collect_affected_agency_ids(session)
    if not affected:
        return
    recorded: set[UUID] = session.info.setdefault(_SESSION_INFO_KEY, set())
    recorded.update(affected)


def _after_commit(session: Session) -> None:
    """Dispatch invalidations for the agencies recorded during flush (Req 10.4).

    Runs after the transaction is durable, guaranteeing the cache delete lands
    only once the DB change is committed and reflected by a subsequent DB
    reload (Req 10.5). The recorded set is cleared so a reused session does not
    re-invalidate stale entries.
    """
    recorded = session.info.pop(_SESSION_INFO_KEY, None)
    if not recorded:
        return
    _dispatch_invalidations(recorded)


def _after_rollback(session: Session) -> None:
    """Drop pending invalidations when the transaction is rolled back.

    A rolled-back change never became durable, so its agencies must not be
    invalidated (the cached list still matches the committed DB state).
    """
    session.info.pop(_SESSION_INFO_KEY, None)


def register_customer_cache_invalidation(target: Any = Session) -> None:  # noqa: ANN401
    """Register the flush/commit/rollback listeners on ``target`` (idempotent).

    ``target`` defaults to the :class:`~sqlalchemy.orm.Session` class so every
    session (including the async engine's underlying sync session) is covered.
    Registration is guarded so repeated calls (e.g. re-imports in tests) do not
    attach duplicate listeners.
    """
    if not event.contains(target, "after_flush", _after_flush):
        event.listen(target, "after_flush", _after_flush)
    if not event.contains(target, "after_commit", _after_commit):
        event.listen(target, "after_commit", _after_commit)
    if not event.contains(target, "after_rollback", _after_rollback):
        event.listen(target, "after_rollback", _after_rollback)


__all__ = [
    "invalidate_agency_customer_cache",
    "on_customer_added",
    "on_customer_removed",
    "on_customer_suspended",
    "on_customer_activated",
    "collect_affected_agency_ids",
    "register_customer_cache_invalidation",
    "set_cache_invalidation_scheduler",
    "Scheduler",
]

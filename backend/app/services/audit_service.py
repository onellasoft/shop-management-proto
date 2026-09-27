"""Audit_Service — records mutations and serves queries/exports (Req 14, 15).

The :class:`AuditService` is the backend component responsible for audit logs.
It has two responsibilities:

* **write path** — :meth:`AuditService.enqueue` pushes a captured
  :class:`~app.audit.mutation_capture.AuditEntry` onto the Celery
  ``write_audit_log`` task (Req 14.5, 14.7). Enqueue is non-blocking and is
  invoked only *after* the originating transaction commits, so the request is
  never blocked on the audit write.
* **read path** — :meth:`AuditService.query` (Task 22.1, Req 15.1-15.5) and
  :meth:`AuditService.export` (Task 22.2, Req 15.6) serve tenant-isolated,
  filtered, ordered, paginated reads of ``audit_logs``.

Tenant isolation for the read path
-----------------------------------
``audit_logs`` carries **both** ``agency_id`` and ``customer_id`` as plain
(non-FK) columns. The generic :func:`app.db.tenant_query.tenant_query` helper
prefers ``customer_id`` whenever a model exposes it, filtering
``customer_id IN customer_scope`` for *every* non-superadmin. That is wrong for
an **agencyadmin** reading audit logs: an agencyadmin is scoped to an *agency*
(Req 15.2), and audit rows record the agency identifier directly, so the
agencyadmin must be filtered by ``agency_id == agency_scope`` — not by the
agencyadmin's ``customer_scope`` (which, while it happens to enumerate the
agency's customers, would miss agency-level rows whose ``customer_id`` is null
and couples the audit filter to cache-derived customer sets).

For that reason this service implements **audit-specific scoping** rather than
reusing ``tenant_query`` blindly (see design "Query & Export API", Req 15.1-15.3):

* **superadmin** — no tenant boundary; all logs (Req 15.1).
* **agencyadmin** — ``agency_id == ctx.agency_scope`` (Req 15.2). If the agency
  scope is absent the query fails closed (matches nothing).
* **customeradmin** (and any other non-superadmin) — ``customer_id IN
  ctx.customer_scope`` (Req 15.3). An empty scope yields ``IN ()`` → zero rows,
  the intended fail-closed boundary.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from sqlalchemy import Select, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidDateRangeError
from app.core.tenant_context import TenantContext
from app.models.audit import AuditLog

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.audit.mutation_capture import AuditEntry


# Pagination bounds (Req 15.5) and export cap (Req 15.6).
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
EXPORT_MAX_RECORDS = 100_000

# The columns emitted (in order) by a CSV/JSON export row.
_EXPORT_FIELDS = (
    "id",
    "user_id",
    "role_type",
    "agency_id",
    "customer_id",
    "module",
    "sub_module",
    "resource",
    "action",
    "old_value",
    "new_value",
    "impersonation",
    "impersonator_user_id",
    "created_at",
)


@dataclass(frozen=True)
class AuditFilter:
    """AND-combined audit query filters (Req 15.4).

    Every supplied field narrows the result set; unspecified (``None``) fields
    impose no constraint. ``date_from``/``date_to`` bound ``created_at``
    inclusively. ``resource`` maps the design's "entity type" filter to the
    permission-graph resource name; ``module`` is offered as an additional
    convenience filter over the same graph. All filters combine with AND.
    """

    date_from: datetime | None = None
    date_to: datetime | None = None
    action: str | None = None
    user_id: UUID | None = None
    resource: str | None = None
    module: str | None = None

    def validate(self) -> None:
        """Reject an inverted date range (Req 15.4).

        A ``date_from`` strictly later than ``date_to`` is a client error and is
        surfaced as :class:`InvalidDateRangeError` (HTTP 422) before any query
        runs.
        """
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise InvalidDateRangeError(
                details={
                    "date_from": self.date_from.isoformat(),
                    "date_to": self.date_to.isoformat(),
                }
            )


@dataclass(frozen=True)
class Page:
    """A single page of audit query results (Req 15.5)."""

    items: list[AuditLog]
    page: int
    page_size: int
    total: int

    @property
    def has_more(self) -> bool:
        """Whether further pages exist beyond this one."""
        return self.page * self.page_size < self.total


class AuditService:
    """Records mutations and serves audit queries/exports (Req 14, 15)."""

    def __init__(self, session: AsyncSession | None = None) -> None:
        """Bind an :class:`AsyncSession` for the read path.

        The write path (:meth:`enqueue`) needs no session — it only dispatches a
        Celery task — so ``session`` is optional and defaults to ``None`` to
        keep ``AuditService()`` construction cheap for enqueue-only callers.
        """
        self._session = session

    # ------------------------------------------------------------------
    # Write path (Req 14.5)
    # ------------------------------------------------------------------
    def enqueue(self, entry: AuditEntry) -> None:
        """Push the audit write task to Celery. Non-blocking (Req 14.5).

        Serializes ``entry`` to a JSON-safe dict (the Celery app uses the JSON
        serializer) and dispatches ``write_audit_log`` via ``.delay``. The
        import is local so constructing the service never forces Celery/broker
        configuration to load at import time.
        """
        from app.tasks.audit_tasks import write_audit_log

        write_audit_log.delay(entry.to_dict())

    # ------------------------------------------------------------------
    # Read path — scoping + filtering (Req 15.1-15.5)
    # ------------------------------------------------------------------
    @staticmethod
    def _scoped_select(ctx: TenantContext) -> Select:
        """Return ``select(AuditLog)`` scoped to ``ctx`` (Req 15.1-15.3).

        Audit-specific scoping (see module docstring): superadmin unfiltered;
        agencyadmin by ``agency_id``; every other non-superadmin by
        ``customer_id IN customer_scope`` (empty scope → zero rows).
        """
        stmt = select(AuditLog)

        # Req 15.1 — superadmin: all logs, no tenant boundary.
        if ctx.is_superadmin:
            return stmt

        # Req 15.2 — agencyadmin: rows for the requester's single agency. If the
        # agency scope is missing we must not leak, so fail closed.
        if ctx.role_type == "agencyadmin":
            if ctx.agency_scope is None:
                return stmt.where(false())
            return stmt.where(AuditLog.agency_id == ctx.agency_scope)

        # Req 15.3 — customeradmin (and any other non-superadmin): rows for the
        # assigned customers. Empty scope → ``IN ()`` → zero rows (fail-closed).
        return stmt.where(AuditLog.customer_id.in_(ctx.customer_scope))

    @staticmethod
    def _apply_filters(stmt: Select, filters: AuditFilter) -> Select:
        """Apply the AND-combined filters to ``stmt`` (Req 15.4).

        Only supplied (non-``None``) filters add a constraint. ``date_from`` /
        ``date_to`` bound ``created_at`` inclusively; ``resource`` matches the
        entity type; ``module`` narrows by permission-graph module.
        """
        if filters.date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(AuditLog.created_at <= filters.date_to)
        if filters.action is not None:
            stmt = stmt.where(AuditLog.action == filters.action)
        if filters.user_id is not None:
            stmt = stmt.where(AuditLog.user_id == filters.user_id)
        if filters.resource is not None:
            stmt = stmt.where(AuditLog.resource == filters.resource)
        if filters.module is not None:
            stmt = stmt.where(AuditLog.module == filters.module)
        return stmt

    @classmethod
    def _clamp_page_size(cls, page_size: int) -> int:
        """Clamp ``page_size`` into ``[1, MAX_PAGE_SIZE]`` (Req 15.5).

        A non-positive page size falls back to the default; anything above the
        maximum is clamped down to :data:`MAX_PAGE_SIZE` rather than rejected, so
        an over-large request still returns a valid (capped) page.
        """
        if page_size <= 0:
            return DEFAULT_PAGE_SIZE
        return min(page_size, MAX_PAGE_SIZE)

    async def query(
        self,
        ctx: TenantContext,
        filters: AuditFilter | None = None,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Page:
        """Return a tenant-isolated, filtered, ordered, paginated page (Req 15.1-15.5).

        Applies audit-specific tenant scoping (Req 15.1-15.3) and the
        AND-combined filters (Req 15.4), orders by ``created_at`` descending, and
        paginates with the default page size 50 / maximum 200 (Req 15.5). An
        inverted date range is rejected up front (Req 15.4).

        Parameters
        ----------
        ctx:
            The requester's immutable tenant context, governing which logs are
            visible.
        filters:
            The AND-combined filters; ``None`` means no filters.
        page:
            1-based page number (values below 1 are treated as page 1).
        page_size:
            Requested page size; clamped into ``[1, 200]`` (Req 15.5).

        Returns
        -------
        Page
            The page items plus ``page``, ``page_size`` and the total row count.
        """
        assert self._session is not None, "AuditService.query requires a session"
        filters = filters or AuditFilter()
        filters.validate()  # Req 15.4 — reject start-after-end.

        page = max(page, 1)
        page_size = self._clamp_page_size(page_size)

        scoped = self._apply_filters(self._scoped_select(ctx), filters)

        # Total row count for the (scoped + filtered) set, before pagination.
        count_stmt = select(func.count()).select_from(scoped.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one())

        # Req 15.5 — newest first, offset/limit pagination.
        stmt = (
            scoped.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(stmt)).scalars().all())

        return Page(items=items, page=page, page_size=page_size, total=total)

    # ------------------------------------------------------------------
    # Read path — export (Req 15.6)
    # ------------------------------------------------------------------
    async def export(
        self,
        ctx: TenantContext,
        filters: AuditFilter | None = None,
        fmt: Literal["csv", "json"] = "csv",
    ) -> bytes:
        """Export matching logs as CSV or JSON, capped at 100,000 (Req 15.6).

        Uses the same tenant scoping and filters as :meth:`query`, orders by
        ``created_at`` descending, and hard-limits the result to
        :data:`EXPORT_MAX_RECORDS` rows. Returns the encoded bytes; the router
        sets the media type (``text/csv`` or ``application/json``) and the
        download filename.

        Parameters
        ----------
        ctx:
            The requester's tenant context (same isolation as :meth:`query`).
        filters:
            The AND-combined filters; ``None`` means no filters.
        fmt:
            ``"csv"`` or ``"json"``.

        Returns
        -------
        bytes
            The UTF-8 encoded export payload.
        """
        assert self._session is not None, "AuditService.export requires a session"
        filters = filters or AuditFilter()
        filters.validate()  # Req 15.4 — reject start-after-end here too.

        # Req 15.6 — newest first, hard cap at 100,000 records.
        stmt = (
            self._apply_filters(self._scoped_select(ctx), filters)
            .order_by(AuditLog.created_at.desc())
            .limit(EXPORT_MAX_RECORDS)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())

        if fmt == "json":
            return self._to_json(rows)
        return self._to_csv(rows)

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _row_value(row: AuditLog, field: str) -> Any:
        """Return a JSON-safe value for ``field`` on an audit ``row``."""
        value = getattr(row, field)
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @classmethod
    def _to_json(cls, rows: list[AuditLog]) -> bytes:
        """Serialize ``rows`` to a JSON array of objects (Req 15.6)."""
        payload = [
            {field: cls._row_value(row, field) for field in _EXPORT_FIELDS}
            for row in rows
        ]
        return json.dumps(payload).encode("utf-8")

    @classmethod
    def _to_csv(cls, rows: list[AuditLog]) -> bytes:
        """Serialize ``rows`` to CSV with a header row (Req 15.6).

        ``old_value``/``new_value`` are jsonb dicts; they are compact-JSON
        encoded so each cell is a single stable string rather than a Python
        ``repr``.
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_EXPORT_FIELDS)
        for row in rows:
            cells: list[Any] = []
            for field in _EXPORT_FIELDS:
                value = cls._row_value(row, field)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                cells.append("" if value is None else value)
            writer.writerow(cells)
        return buffer.getvalue().encode("utf-8")


_audit_service: AuditService | None = None


def get_audit_service() -> AuditService:
    """Return the process-wide enqueue-only :class:`AuditService` singleton.

    This singleton has no bound session and is intended for the write path only.
    Read-path callers construct a request-scoped ``AuditService(session)``.
    """
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service


__all__ = [
    "AuditService",
    "AuditFilter",
    "Page",
    "get_audit_service",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "EXPORT_MAX_RECORDS",
]

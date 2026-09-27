"""Audit query and export router (``/audit``) — Task 22.3.

Exposes the two compliance read endpoints for audit logs (Req 15.1, 15.6):

* ``GET /audit/logs`` — a tenant-isolated, filtered, ordered, paginated query
  over ``audit_logs`` (Req 15.1-15.5). Filters (date range, action, user,
  resource/entity type, module) are AND-combined and results come back newest
  first, paginated (default page size 50, max 200).
* ``GET /audit/logs/export?format=csv|json`` — the same scoped/filtered result
  set exported as a downloadable CSV or JSON file, capped at 100,000 records
  (Req 15.6).

Authorization & isolation
-------------------------
Both endpoints require only an **authenticated** request: they depend on
:func:`app.api.deps.get_tenant_context`, which returns the immutable
:class:`TenantContext` attached by the auth/tenant middleware and fails closed
with ``tenant_context_missing`` when absent (Req 9.8). They are deliberately
**not** gated by :func:`require_permission`: audit querying is a capability of
the fixed roles governed by the requester's tenant scope (superadmin all /
agencyadmin their agency / customeradmin their assigned customers, Req 15.1-15.3)
rather than a module Action in the seeded permission graph — inventing an
``action_key`` for it would be arbitrary. The requester's tenant scope alone
governs visibility; :class:`~app.services.audit_service.AuditService` enforces
the isolation in the query itself.
"""

from __future__ import annotations

import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.schemas.audit import AuditLogItem, AuditLogPage
from app.services.audit_service import AuditFilter, AuditService

# Single router for all /audit endpoints.
router = APIRouter(prefix="/audit", tags=["audit"])

# Media types + filename stems for each export format (Req 15.6).
_EXPORT_MEDIA_TYPES: dict[str, str] = {
    "csv": "text/csv",
    "json": "application/json",
}


def _build_filter(
    date_from: datetime.datetime | None,
    date_to: datetime.datetime | None,
    action: str | None,
    user_id: UUID | None,
    resource: str | None,
    module: str | None,
) -> AuditFilter:
    """Assemble an :class:`AuditFilter` from the query parameters (Req 15.4)."""
    return AuditFilter(
        date_from=date_from,
        date_to=date_to,
        action=action,
        user_id=user_id,
        resource=resource,
        module=module,
    )


@router.get(
    "/logs",
    response_model=AuditLogPage,
    status_code=status.HTTP_200_OK,
    summary="Query audit logs (tenant-isolated, filtered, paginated)",
)
async def query_audit_logs(
    date_from: datetime.datetime | None = Query(
        default=None, description="Inclusive lower bound on created_at."
    ),
    date_to: datetime.datetime | None = Query(
        default=None, description="Inclusive upper bound on created_at."
    ),
    action: str | None = Query(default=None, description="Filter by action name."),
    user_id: UUID | None = Query(default=None, description="Filter by actor id."),
    resource: str | None = Query(
        default=None, description="Filter by resource (entity type)."
    ),
    module: str | None = Query(default=None, description="Filter by module name."),
    page: int = Query(default=1, ge=1, description="1-based page number."),
    page_size: int = Query(
        default=50,
        ge=1,
        description="Page size; clamped to at most 200.",
    ),
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> AuditLogPage:
    """Return a page of audit logs within the requester's scope (Req 15.1-15.5).

    Delegates to :meth:`AuditService.query`, which applies audit-specific tenant
    isolation (superadmin all / agencyadmin their agency / customeradmin their
    assigned customers), the AND-combined filters, ``created_at`` descending
    ordering, and pagination (default 50, max 200). An inverted date range is
    rejected with ``invalid_date_range`` (422).
    """
    service = AuditService(session)
    result = await service.query(
        ctx,
        _build_filter(date_from, date_to, action, user_id, resource, module),
        page=page,
        page_size=page_size,
    )
    return AuditLogPage(
        items=[AuditLogItem.model_validate(row) for row in result.items],
        page=result.page,
        page_size=result.page_size,
        total=result.total,
        has_more=result.has_more,
    )


@router.get(
    "/logs/export",
    status_code=status.HTTP_200_OK,
    summary="Export audit logs as a downloadable CSV or JSON file",
    responses={
        200: {
            "content": {"text/csv": {}, "application/json": {}},
            "description": "The exported audit logs (≤100,000 records).",
        }
    },
)
async def export_audit_logs(
    format: Literal["csv", "json"] = Query(
        default="csv", description="Export format: csv or json."
    ),
    date_from: datetime.datetime | None = Query(
        default=None, description="Inclusive lower bound on created_at."
    ),
    date_to: datetime.datetime | None = Query(
        default=None, description="Inclusive upper bound on created_at."
    ),
    action: str | None = Query(default=None, description="Filter by action name."),
    user_id: UUID | None = Query(default=None, description="Filter by actor id."),
    resource: str | None = Query(
        default=None, description="Filter by resource (entity type)."
    ),
    module: str | None = Query(default=None, description="Filter by module name."),
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Export the scoped/filtered audit logs as a downloadable file (Req 15.6).

    Delegates to :meth:`AuditService.export`, which applies the same tenant
    isolation and filters as the query, orders by ``created_at`` descending, and
    caps the export at 100,000 records. Returns the encoded bytes with the
    matching media type (``text/csv`` / ``application/json``) and a
    ``Content-Disposition: attachment`` header so browsers download the file.
    """
    service = AuditService(session)
    payload = await service.export(
        ctx,
        _build_filter(date_from, date_to, action, user_id, resource, module),
        fmt=format,
    )
    media_type = _EXPORT_MEDIA_TYPES[format]
    filename = f"audit_logs.{format}"
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]

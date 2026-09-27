"""Pydantic v2 response schemas for the audit query endpoint.

Backs ``GET /audit/logs`` (Task 22.3). The query endpoint returns a page of
audit records shaped by :class:`AuditLogItem` inside a :class:`AuditLogPage`
envelope carrying the pagination metadata (Req 15.5). The export endpoint
(``GET /audit/logs/export``) streams raw CSV/JSON bytes and therefore has no
Pydantic response model.

Filter query parameters (date range, action, user, resource/entity type,
module) are declared directly on the router endpoint and mapped to
:class:`~app.services.audit_service.AuditFilter`; they are AND-combined
(Req 15.4).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogItem(BaseModel):
    """A single audit log record returned by a query (Req 15.1-15.5).

    Mirrors the persisted :class:`~app.models.audit.AuditLog` columns: the
    actor and role, the tenant identifiers of the active context, the mutated
    permission-graph names, the before/after diff, the impersonation indicator
    and impersonator, and the creation timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="The audit log's unique id.")
    user_id: uuid.UUID = Field(..., description="The actor who performed the mutation.")
    role_type: str | None = Field(
        default=None, description="The actor's role type at the time."
    )
    agency_id: uuid.UUID | None = Field(
        default=None, description="Agency identifier of the active context."
    )
    customer_id: uuid.UUID | None = Field(
        default=None, description="Customer identifier of the active context."
    )
    module: str | None = Field(default=None, description="The mutated Module name.")
    sub_module: str | None = Field(
        default=None, description="The mutated SubModule name."
    )
    resource: str | None = Field(
        default=None, description="The mutated Resource (entity type)."
    )
    action: str | None = Field(default=None, description="The Action performed.")
    old_value: Any | None = Field(
        default=None, description="The value before the mutation (empty on create)."
    )
    new_value: Any | None = Field(
        default=None, description="The value after the mutation (empty on delete)."
    )
    impersonation: bool = Field(
        ..., description="True when performed during an impersonation session."
    )
    impersonator_user_id: uuid.UUID | None = Field(
        default=None, description="The impersonator's id when impersonating."
    )
    created_at: datetime.datetime = Field(
        ..., description="When the mutation was recorded."
    )


class AuditLogPage(BaseModel):
    """A page of audit query results with pagination metadata (Req 15.5)."""

    items: list[AuditLogItem] = Field(
        default_factory=list, description="The audit logs on this page (newest first)."
    )
    page: int = Field(..., description="The 1-based page number returned.")
    page_size: int = Field(
        ..., description="The effective page size (clamped to at most 200)."
    )
    total: int = Field(
        ..., description="Total matching records across all pages (scoped + filtered)."
    )
    has_more: bool = Field(
        ..., description="Whether further pages exist beyond this one."
    )


__all__ = ["AuditLogItem", "AuditLogPage"]

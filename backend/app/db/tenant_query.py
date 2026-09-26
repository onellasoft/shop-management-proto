"""Application-level tenant filtering and mutation re-verification (Req 9).

This module centralizes the tenant WHERE scope so every read and mutation is
filtered consistently. Filtering is done at the application/ORM layer rather
than with PostgreSQL row-level security — chosen for clarity and auditability
(see design "Tenant Isolation Mechanism → ORM Auto-Filtering Mixin").

Two helpers are provided:

* :func:`tenant_query` — builds a ``select(model)`` with the tenant WHERE scope
  derived from an immutable :class:`~app.core.tenant_context.TenantContext`.
* :func:`verify_tenant_scope` — re-verifies that a specific row's
  ``agency_id`` / ``customer_id`` falls within the acting context before a
  mutation is applied, raising :class:`TenantBoundaryViolationError` otherwise.

Both are deliberately **fail-closed**: any principal that is not a superadmin
and whose scope cannot be satisfied matches zero rows / is rejected, so a model
or row that cannot be tenant-scoped never leaks data (Req 9.7).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import false, select
from sqlalchemy.sql import Select

from app.core.errors import TenantBoundaryViolationError
from app.core.tenant_context import TenantContext


def tenant_query(model: Any, ctx: TenantContext) -> Select:
    """Build a ``select(model)`` scoped to the caller's tenant (Req 9.2–9.7).

    The WHERE scope is derived from ``ctx`` following the design's reference
    factory:

    * **superadmin** (``ctx.is_superadmin``) — no tenant boundary; the query is
      returned unfiltered. This is the *only* no-filter case (Req 9.3).
    * model has a ``customer_id`` column — filter
      ``model.customer_id IN ctx.customer_scope``. ``customer_scope`` already
      encodes the correct accessible set for agencyadmin, customeradmin, and
      custom-role principals (built by ``build_tenant_context``). A non-superadmin
      with an **empty** ``customer_scope`` yields ``IN ()`` which matches zero
      rows — the intended fail-closed behavior (Req 9.4, 9.5, 9.6).
    * else model has an ``agency_id`` column and ``ctx.agency_scope`` is set —
      filter ``model.agency_id == ctx.agency_scope``.
    * otherwise — fail-closed: match nothing so a model that cannot be
      tenant-scoped never leaks rows (Req 9.7).

    Parameters
    ----------
    model:
        A SQLAlchemy declarative model (typically one carrying ``customer_id`` /
        ``agency_id`` via :class:`~app.db.mixins.TenantMixin`).
    ctx:
        The immutable tenant context for the current request.

    Returns
    -------
    Select
        A ``select`` statement with the tenant WHERE clause applied.
    """
    stmt = select(model)

    # Req 9.3 — superadmin has no tenant boundary. This is the ONLY case that
    # returns an unfiltered query; every other branch applies a scope or fails
    # closed.
    if ctx.is_superadmin:
        return stmt

    # Req 9.4/9.5/9.6 — customer-scoped model. An empty customer_scope produces
    # ``IN ()`` which matches zero rows; we must NOT collapse that into "no
    # filter" — the empty set is a legitimate fail-closed boundary.
    if hasattr(model, "customer_id"):
        return stmt.where(model.customer_id.in_(ctx.customer_scope))

    # Agency-scoped model (no customer_id). Only applies when the context
    # actually carries an agency scope.
    if hasattr(model, "agency_id") and ctx.agency_scope is not None:
        return stmt.where(model.agency_id == ctx.agency_scope)

    # Req 9.7 — fail-closed default: the model cannot be tenant-scoped for this
    # principal, so it must match nothing rather than leak rows.
    return stmt.where(false())


def verify_tenant_scope(
    *,
    ctx: TenantContext,
    agency_id: UUID | None = None,
    customer_id: UUID | None = None,
) -> None:
    """Re-verify a targeted row's tenant is within scope before mutating it.

    Reads are filtered by :func:`tenant_query`, but a mutation that targets a
    specific row (loaded by primary key, say) must re-confirm the row's tenant
    identifiers fall within the acting context — otherwise a caller could mutate
    a row outside its boundary (Req 9.2, 9.7, 4.4). Call this in the service
    layer immediately before applying the mutation.

    Rules:

    * **superadmin** always passes — no tenant boundary (Req 4.2, 9.3).
    * if a ``customer_id`` is supplied, it must be a member of
      ``ctx.customer_scope``.
    * else if an ``agency_id`` is supplied, it must equal ``ctx.agency_scope``.
    * if neither identifier is supplied for a non-superadmin, the row cannot be
      shown to be in scope, so verification fails closed.

    Parameters
    ----------
    ctx:
        The immutable tenant context for the current request.
    agency_id:
        The targeted row's ``agency_id`` (if the row is agency-scoped).
    customer_id:
        The targeted row's ``customer_id`` (if the row is customer-scoped).

    Raises
    ------
    TenantBoundaryViolationError
        When the row's tenant is outside the caller's context (Req 9.2, 9.7,
        4.4).
    """
    # Req 4.2/9.3 — superadmin bypasses the tenant boundary entirely.
    if ctx.is_superadmin:
        return

    if customer_id is not None:
        if customer_id in ctx.customer_scope:
            return
        raise TenantBoundaryViolationError(
            details={"customer_id": str(customer_id)},
        )

    if agency_id is not None:
        if ctx.agency_scope is not None and agency_id == ctx.agency_scope:
            return
        raise TenantBoundaryViolationError(
            details={"agency_id": str(agency_id)},
        )

    # Req 9.7 — no tenant identifier to check for a non-superadmin: fail closed.
    raise TenantBoundaryViolationError(
        details={"reason": "no_tenant_identifier"},
    )


__all__ = ["tenant_query", "verify_tenant_scope"]

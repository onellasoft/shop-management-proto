"""In-memory, immutable tenant context (Req 9.1).

The :class:`TenantContext` is the authoritative, per-request description of
*who* is acting and *what* tenant scope they may touch. It is built once by
the auth/tenant middleware (from the verified access token plus any active
impersonation) and attached to ``request.state.tenant_context`` for the
lifetime of the request.

Because it is a frozen dataclass it cannot be mutated after construction,
which prevents any downstream code from widening a caller's scope mid-request.

Scope semantics (see design "TenantContext (in-memory, immutable)"):

* ``customer_scope`` is authoritative for tenant filtering.
* For a superadmin, ``is_superadmin=True`` short-circuits all filters
  (``customer_scope`` is empty, meaning "no filter").
* Under impersonation, the derived scope reflects the impersonated entity
  rather than the impersonator (Req 12.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class TenantContext:
    """Immutable snapshot of the acting principal's tenant scope (Req 9.1)."""

    user_id: UUID
    role_type: str
    """One of ``superadmin`` | ``agencyadmin`` | ``customeradmin``."""

    agency_scope: UUID | None
    """The agencyadmin's single agency; ``None`` for other roles."""

    customer_scope: frozenset[UUID]
    """Accessible customer ids. Empty for superadmin (= no filter)."""

    is_superadmin: bool
    """When true, short-circuits all tenant filters."""

    impersonating: bool
    """True while acting through an active impersonation session."""

    impersonated_agency_id: UUID | None
    impersonated_customer_id: UUID | None
    impersonator_user_id: UUID | None
    custom_role_customer_id: UUID | None
    """Set when acting under a custom role (single-customer scope)."""

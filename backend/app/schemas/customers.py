"""Pydantic v2 request/response schemas for the customers & staff management endpoints.

Backs the ``/customers`` router. Covers:

* Customer discovery (Req 4.3) — ``GET /customers/me``.
* Staff listing (Req 4.5) — ``GET /customers/{id}/users``.
* Staff invite (Req 4.5) — ``POST /customers/{id}/users``.
* Staff removal — ``DELETE /customers/{id}/users/{uid}``.
* Role assignment replacement — ``PUT /customers/{id}/users/{uid}/roles``.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Customer schemas
# ---------------------------------------------------------------------------


class CustomerSummary(BaseModel):
    """A brief summary of a customer record (Req 4.3).

    Returned by ``GET /customers/me`` so callers can discover which customers
    they manage.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Customer primary key.")
    name: str = Field(..., description="Customer display name.")
    status: str = Field(..., description="Customer status (active / suspended).")
    agency_id: uuid.UUID = Field(..., description="The owning agency's primary key.")


# ---------------------------------------------------------------------------
# Staff member schemas
# ---------------------------------------------------------------------------


class RoleAssignment(BaseModel):
    """A single custom role assigned to a staff member within a customer.

    Part of :class:`StaffMember` for displaying the staff member's role set.
    """

    model_config = ConfigDict(from_attributes=True)

    role_id: uuid.UUID = Field(..., description="Role primary key.")
    role_name: str = Field(..., description="Role display name.")


class StaffMember(BaseModel):
    """A user associated with a customer, with their role assignments.

    ``name`` is derived from the email prefix (everything before ``@``) because
    the ``users`` table has no dedicated name column.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID = Field(..., description="User primary key.")
    email: str | None = Field(default=None, description="User email address.")
    name: str = Field(
        ...,
        description="Display name derived from the email prefix.",
    )
    mobile: str | None = Field(default=None, description="User mobile number.")
    status: str = Field(..., description="User account status.")
    roles: list[RoleAssignment] = Field(
        default_factory=list,
        description="Custom roles assigned to this user within the customer.",
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class InviteStaffRequest(BaseModel):
    """Payload for ``POST /customers/{customer_id}/users`` — invite a staff member.

    ``role_ids`` is optional; an empty list means no custom roles are assigned
    at invite time.
    """

    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Email address of the staff member to invite.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Display name for the invited staff member.",
    )
    role_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Optional list of custom role IDs to assign on invite.",
    )


class UpdateStaffRolesRequest(BaseModel):
    """Payload for ``PUT /customers/{customer_id}/users/{user_id}/roles``.

    Replaces the user's entire role set within the customer. An empty list
    removes all role assignments.
    """

    role_ids: list[uuid.UUID] = Field(
        ...,
        description="The complete desired set of custom role IDs for this user.",
    )


__all__ = [
    "CustomerSummary",
    "RoleAssignment",
    "StaffMember",
    "InviteStaffRequest",
    "UpdateStaffRolesRequest",
]

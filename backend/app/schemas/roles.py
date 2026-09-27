"""Pydantic v2 request/response schemas for the role management endpoints.

Backs the ``/roles`` and ``/permissions/tree`` router (Task 11.3). Covers:

* Custom-role lifecycle (Req 7.2, 7.3, 7.4) — create, clone, rename, delete.
* Action assignment (Req 7.5–7.9) — ``PUT /roles/{id}/actions``.
* Permission catalog (Req 5.1, 5.2) — ``GET /permissions/tree`` returns the
  full Module → SubModule → Resource → Action hierarchy with real UUIDs so the
  frontend can pass action ids to the assignment endpoint.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Role response schemas
# ---------------------------------------------------------------------------


class RoleResponse(BaseModel):
    """A fixed system role or a custom role (Req 7.2, 7.3).

    Both fixed roles (``is_custom=False``, ``role_type`` set) and custom roles
    (``is_custom=True``, ``customer_id`` set) are represented by this schema.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Role primary key.")
    role_type: str | None = Field(
        default=None,
        description="Fixed role type (superadmin/agencyadmin/customeradmin). Null for custom roles.",
    )
    is_custom: bool = Field(..., description="True for custom roles scoped to a customer.")
    customer_id: uuid.UUID | None = Field(
        default=None,
        description="The customer that owns this custom role. Null for fixed roles.",
    )
    name: str | None = Field(
        default=None,
        description="Role display name. Set for custom roles.",
    )


class RoleWithActionsResponse(RoleResponse):
    """A custom role with its current action grants (Req 7.5).

    Returned by create, clone, and assign-actions endpoints so the caller
    immediately sees the full action set without an extra round-trip.
    """

    action_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="IDs of the Actions currently granted to this role.",
    )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateRoleRequest(BaseModel):
    """Payload for ``POST /roles`` (Req 7.2, 7.3)."""

    customer_id: uuid.UUID = Field(
        ...,
        description="The customer to scope this custom role to.",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique name for the role within the customer (1–100 chars).",
    )


class CloneRoleRequest(BaseModel):
    """Payload for ``POST /roles/{role_id}/clone`` (Req 7.4)."""

    new_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Name for the cloned role (1–100 chars, unique within the customer).",
    )


class UpdateRoleRequest(BaseModel):
    """Payload for ``PATCH /roles/{role_id}`` (Req 7.3)."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="New name for the custom role (1–100 chars, unique within the customer).",
    )


class AssignActionsRequest(BaseModel):
    """Payload for ``PUT /roles/{role_id}/actions`` (Req 7.5–7.9).

    Replaces the role's action set entirely. Only actions belonging to
    modules that are currently subscribed by the role's customer may be
    assigned (Req 7.5); the subscription gate is enforced by the service.
    """

    action_ids: list[uuid.UUID] = Field(
        ...,
        description="The complete desired set of Action IDs for this role.",
    )


# ---------------------------------------------------------------------------
# Permission tree schemas
# ---------------------------------------------------------------------------


class ActionNode(BaseModel):
    """Leaf node in the permission tree (Req 5.1, 5.2, 13.1)."""

    model_config = ConfigDict(from_attributes=True)

    action_id: uuid.UUID = Field(..., description="Action primary key.")
    name: str = Field(..., description="Action name (create/read/update/delete or custom).")
    action_key: str = Field(
        ...,
        description="Denormalized module.submodule.resource.action key.",
    )
    is_sensitive: bool = Field(
        ...,
        description="True when this action is blocked during impersonation (Req 13.1).",
    )


class ResourceNode(BaseModel):
    """Third level of the permission tree (Req 5.1)."""

    model_config = ConfigDict(from_attributes=True)

    resource_id: uuid.UUID = Field(..., description="Resource primary key.")
    key: str = Field(..., description="Machine key for this resource.")
    name: str = Field(..., description="Display name for this resource.")
    actions: list[ActionNode] = Field(
        default_factory=list,
        description="Actions defined on this resource.",
    )


class SubModuleNode(BaseModel):
    """Second level of the permission tree (Req 5.1)."""

    model_config = ConfigDict(from_attributes=True)

    submodule_id: uuid.UUID = Field(..., description="SubModule primary key.")
    key: str = Field(..., description="Machine key for this submodule.")
    name: str = Field(..., description="Display name for this submodule.")
    resources: list[ResourceNode] = Field(
        default_factory=list,
        description="Resources within this submodule.",
    )


class ModuleNode(BaseModel):
    """Top level of the permission tree (Req 5.1)."""

    model_config = ConfigDict(from_attributes=True)

    module_id: uuid.UUID = Field(..., description="Module primary key.")
    key: str = Field(..., description="Machine key for this module.")
    name: str = Field(..., description="Display name for this module.")
    submodules: list[SubModuleNode] = Field(
        default_factory=list,
        description="Submodules within this module.",
    )


class PermissionsTreeResponse(BaseModel):
    """Full Module → SubModule → Resource → Action catalog (Req 5.1).

    Returned by ``GET /permissions/tree``. UUIDs in this response are real
    database-level ids that the client can pass directly to
    ``PUT /roles/{id}/actions``.
    """

    modules: list[ModuleNode] = Field(
        default_factory=list,
        description="All modules with their full submodule/resource/action tree.",
    )


__all__ = [
    "RoleResponse",
    "RoleWithActionsResponse",
    "CreateRoleRequest",
    "CloneRoleRequest",
    "UpdateRoleRequest",
    "AssignActionsRequest",
    "ActionNode",
    "ResourceNode",
    "SubModuleNode",
    "ModuleNode",
    "PermissionsTreeResponse",
]

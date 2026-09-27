"""Role management router (``/roles``) — Task 11.3.

Exposes seven endpoints for managing custom roles and querying the permission
catalog (Req 7.2, 7.3, 7.4, 7.5):

* ``GET /roles?customer_id=<uuid>`` — list fixed and custom roles for a
  customer (Req 7.3).
* ``POST /roles`` — create a new custom role (Req 7.2, 7.3).
* ``POST /roles/{role_id}/clone`` — clone a custom role (Req 7.4).
* ``PATCH /roles/{role_id}`` — rename a custom role (Req 7.3).
* ``DELETE /roles/{role_id}`` — delete a custom role (Req 7.3).
* ``PUT /roles/{role_id}/actions`` — assign action grants (Req 7.5–7.9).
* ``GET /permissions/tree`` — full Module → SubModule → Resource → Action
  catalog with real UUIDs (Req 5.1).

Authorization
-------------
Custom role management is a customeradmin capability. These endpoints use
:func:`app.api.deps.get_tenant_context` — which requires a valid authenticated
session (Req 9.8) and provides tenant isolation — rather than
:func:`require_permission`, because role management is gated on the fixed role
system rather than a Module Action. The per-customer scope is enforced by
:meth:`~app.services.authorization_service.AuthorizationService._require_single_customer_scope`
within each service method.

Errors
------
Service errors propagate to the central exception handlers:

* :class:`~app.core.errors.RoleNameConflictError` → 409
* :class:`~app.core.errors.NotAuthorizedError` → 403
* :class:`~app.core.errors.ActionModuleUnsubscribedError` → 403
* :class:`~app.core.errors.ValidationError` → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.permission import Action, Module, Resource, SubModule
from app.models.role import Role, RolePermission
from app.schemas.roles import (
    ActionNode,
    AssignActionsRequest,
    CloneRoleRequest,
    CreateRoleRequest,
    ModuleNode,
    PermissionsTreeResponse,
    ResourceNode,
    RoleResponse,
    RoleWithActionsResponse,
    SubModuleNode,
    UpdateRoleRequest,
)
from app.services.authorization_service import AuthorizationService

# Single router for all /roles and /permissions endpoints.
router = APIRouter(tags=["roles"])


# ---------------------------------------------------------------------------
# Helper: load action ids for a role
# ---------------------------------------------------------------------------


async def _load_action_ids(session: AsyncSession, role_id: uuid.UUID) -> list[uuid.UUID]:
    """Return the action ids currently granted to ``role_id``.

    Used to populate ``RoleWithActionsResponse.action_ids`` after create,
    clone, and assign-actions operations so the caller receives the full state
    in a single response.
    """
    rows = (
        await session.execute(
            select(RolePermission.action_id).where(
                RolePermission.role_id == role_id
            )
        )
    ).scalars().all()
    return list(rows)


def _role_with_actions(role: Role, action_ids: list[uuid.UUID]) -> RoleWithActionsResponse:
    """Build a :class:`RoleWithActionsResponse` from an ORM role + action ids."""
    return RoleWithActionsResponse(
        id=role.id,
        role_type=role.role_type,
        is_custom=role.is_custom,
        customer_id=role.customer_id,
        name=role.name,
        action_ids=action_ids,
    )


# ---------------------------------------------------------------------------
# GET /roles
# ---------------------------------------------------------------------------


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    status_code=status.HTTP_200_OK,
    summary="List fixed and custom roles for a customer",
)
async def list_roles(
    customer_id: uuid.UUID = Query(
        ...,
        description="Customer whose roles to list (fixed roles + that customer's custom roles).",
    ),
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> list[RoleResponse]:
    """Return all roles visible to the UI when assigning a role to a staff member (Req 7.3).

    Returns the three fixed system roles (``is_custom=False``) which are
    globally applicable, plus every custom role scoped to ``customer_id``.
    Both are needed so the UI can present the full set of assignable roles.
    """
    # Fixed system roles (no customer scope)
    fixed_stmt = select(Role).where(Role.is_custom.is_(False))
    fixed_roles = (await session.execute(fixed_stmt)).scalars().all()

    # Custom roles belonging to the requested customer
    custom_stmt = select(Role).where(
        Role.is_custom.is_(True),
        Role.customer_id == customer_id,
    )
    custom_roles = (await session.execute(custom_stmt)).scalars().all()

    all_roles = list(fixed_roles) + list(custom_roles)
    return [
        RoleResponse(
            id=r.id,
            role_type=r.role_type,
            is_custom=r.is_custom,
            customer_id=r.customer_id,
            name=r.name,
        )
        for r in all_roles
    ]


# ---------------------------------------------------------------------------
# POST /roles
# ---------------------------------------------------------------------------


@router.post(
    "/roles",
    response_model=RoleWithActionsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role",
)
async def create_role(
    payload: CreateRoleRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> RoleWithActionsResponse:
    """Create a new custom role scoped to ``customer_id`` (Req 7.2, 7.3).

    The name must be unique within the customer (1–100 characters). Returns the
    created role with its current (empty) action set.

    Errors:
    - ``RoleNameConflictError`` → 409 when the name already exists.
    - ``ValidationError`` → 422 when the name is out of bounds.
    """
    service = AuthorizationService(session)
    role = await service.create_custom_role(ctx, payload.customer_id, payload.name)
    action_ids = await _load_action_ids(session, role.id)
    return _role_with_actions(role, action_ids)


# ---------------------------------------------------------------------------
# POST /roles/{role_id}/clone
# ---------------------------------------------------------------------------


@router.post(
    "/roles/{role_id}/clone",
    response_model=RoleWithActionsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a custom role",
)
async def clone_role(
    role_id: uuid.UUID,
    payload: CloneRoleRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> RoleWithActionsResponse:
    """Clone a custom role, copying its action set (Req 7.4).

    Creates a new custom role in the same customer with a unique name, copying
    the source role's action grants. The caller may then add or remove actions
    from the copied set via ``PUT /roles/{id}/actions``.

    Errors:
    - ``NotAuthorizedError`` → 403 when the source role is not accessible.
    - ``RoleNameConflictError`` → 409 when ``new_name`` already exists.
    - ``ValidationError`` → 422 when ``new_name`` is out of bounds.
    """
    service = AuthorizationService(session)
    clone = await service.clone_custom_role(ctx, role_id, payload.new_name)
    action_ids = await _load_action_ids(session, clone.id)
    return _role_with_actions(clone, action_ids)


# ---------------------------------------------------------------------------
# PATCH /roles/{role_id}
# ---------------------------------------------------------------------------


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    status_code=status.HTTP_200_OK,
    summary="Rename a custom role",
)
async def update_role(
    role_id: uuid.UUID,
    payload: UpdateRoleRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> RoleResponse:
    """Rename a custom role within the caller's customer scope (Req 7.3).

    Validates the new name for uniqueness and length (1–100 characters). Returns
    the updated role.

    Errors:
    - ``NotAuthorizedError`` → 403 when the role is not accessible.
    - ``RoleNameConflictError`` → 409 when the new name already exists.
    - ``ValidationError`` → 422 when the name is out of bounds.
    """
    service = AuthorizationService(session)
    role = await service.update_custom_role(ctx, role_id, name=payload.name)
    return RoleResponse(
        id=role.id,
        role_type=role.role_type,
        is_custom=role.is_custom,
        customer_id=role.customer_id,
        name=role.name,
    )


# ---------------------------------------------------------------------------
# DELETE /roles/{role_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role",
)
async def delete_role(
    role_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a custom role and its action grants (Req 7.3).

    The role must be a custom role within the caller's customer scope. Returns
    ``204 No Content`` on success.

    Errors:
    - ``NotAuthorizedError`` → 403 when the role is not accessible.
    """
    service = AuthorizationService(session)
    await service.delete_custom_role(ctx, role_id)


# ---------------------------------------------------------------------------
# PUT /roles/{role_id}/actions
# ---------------------------------------------------------------------------


@router.put(
    "/roles/{role_id}/actions",
    response_model=RoleWithActionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign action grants to a custom role",
)
async def assign_actions(
    role_id: uuid.UUID,
    payload: AssignActionsRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> RoleWithActionsResponse:
    """Replace the role's action set with the requested action ids (Req 7.5–7.9).

    Only actions belonging to modules that are currently subscribed by the
    role's customer may be assigned (Req 7.5). If any action's module is
    unsubscribed or unresolvable the entire assignment is rejected and the
    existing grants are left unchanged (Req 7.6, 7.9).

    Returns the role with its new action set.

    Errors:
    - ``NotAuthorizedError`` → 403 when the role is not accessible.
    - ``ActionModuleUnsubscribedError`` → 403 when any action's module is not
      subscribed.
    """
    service = AuthorizationService(session)
    role = await service.assign_actions(ctx, role_id, payload.action_ids)
    action_ids = await _load_action_ids(session, role.id)
    return _role_with_actions(role, action_ids)


# ---------------------------------------------------------------------------
# GET /permissions/tree
# ---------------------------------------------------------------------------


@router.get(
    "/permissions/tree",
    response_model=PermissionsTreeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the full permission tree",
)
async def get_permissions_tree(
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> PermissionsTreeResponse:
    """Return the full Module → SubModule → Resource → Action catalog (Req 5.1).

    Queries the database for all seeded module/submodule/resource/action rows
    and structures them into the nested response. UUIDs in this response are
    real database-level ids that the client can pass directly to
    ``PUT /roles/{id}/actions``.

    The full tree is returned regardless of subscription state. The UI may use
    ``customer_id`` filtering (not required) to annotate which modules are
    subscribed; here we return the complete catalog and let the UI gray out
    unsubscribed modules.
    """
    # Load all modules with their full graph in one query per level.
    modules_rows = (
        await session.execute(select(Module).order_by(Module.name))
    ).scalars().all()

    # Load submodules, resources, and actions in bulk to avoid N+1 queries.
    submodules_rows = (
        await session.execute(
            select(SubModule).order_by(SubModule.module_id, SubModule.name)
        )
    ).scalars().all()

    resources_rows = (
        await session.execute(
            select(Resource).order_by(Resource.submodule_id, Resource.name)
        )
    ).scalars().all()

    actions_rows = (
        await session.execute(
            select(Action).order_by(Action.resource_id, Action.name)
        )
    ).scalars().all()

    # Index child rows by parent id for O(1) lookup.
    submodules_by_module: dict[uuid.UUID, list[SubModule]] = {}
    for sm in submodules_rows:
        submodules_by_module.setdefault(sm.module_id, []).append(sm)

    resources_by_submodule: dict[uuid.UUID, list[Resource]] = {}
    for res in resources_rows:
        resources_by_submodule.setdefault(res.submodule_id, []).append(res)

    actions_by_resource: dict[uuid.UUID, list[Action]] = {}
    for act in actions_rows:
        actions_by_resource.setdefault(act.resource_id, []).append(act)

    # Assemble the nested tree.
    module_nodes: list[ModuleNode] = []
    for mod in modules_rows:
        submodule_nodes: list[SubModuleNode] = []
        for sm in submodules_by_module.get(mod.id, []):
            resource_nodes: list[ResourceNode] = []
            for res in resources_by_submodule.get(sm.id, []):
                action_nodes: list[ActionNode] = [
                    ActionNode(
                        action_id=act.id,
                        name=act.name,
                        action_key=act.action_key,
                        is_sensitive=act.is_sensitive,
                    )
                    for act in actions_by_resource.get(res.id, [])
                ]
                resource_nodes.append(
                    ResourceNode(
                        resource_id=res.id,
                        key=res.key,
                        name=res.name,
                        actions=action_nodes,
                    )
                )
            submodule_nodes.append(
                SubModuleNode(
                    submodule_id=sm.id,
                    key=sm.key,
                    name=sm.name,
                    resources=resource_nodes,
                )
            )
        module_nodes.append(
            ModuleNode(
                module_id=mod.id,
                key=mod.key,
                name=mod.name,
                submodules=submodule_nodes,
            )
        )

    return PermissionsTreeResponse(modules=module_nodes)


__all__ = ["router"]

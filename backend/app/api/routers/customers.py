"""Customers & staff management router (``/customers``).

Exposes five endpoints for discovering customers and managing staff members
(Req 4.3, 4.5):

* ``GET /customers/me`` — list customers the authenticated user manages.
* ``GET /customers/{customer_id}/users`` — list staff members for a customer.
* ``POST /customers/{customer_id}/users`` — invite a new staff member.
* ``DELETE /customers/{customer_id}/users/{user_id}`` — remove a staff member.
* ``PUT /customers/{customer_id}/users/{user_id}/roles`` — replace role assignments.

Authorization
-------------
All endpoints use :func:`app.api.deps.get_tenant_context` (requires a valid
authenticated session, Req 9.8).  Customer-level access is enforced inline:
callers may only touch customers within their own ``customer_scope``, or
everything if they are superadmin.

Invite tokens
-------------
In development mode (:attr:`~app.core.config.Settings.is_development`), the
invite link is logged to stdout rather than dispatched via email. The token is
stored in Redis with a 7-day TTL under the key ``invite:{token}``.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_tenant_context
from app.cache.redis_client import get_redis
from app.core.config import settings
from app.core.errors import NotAuthorizedError, UserAlreadyInCustomerError
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.customer import Customer
from app.models.customer_user import CustomerUser
from app.models.role import Role, UserRole
from app.models.user import User
from app.schemas.customers import (
    CustomerSummary,
    InviteStaffRequest,
    RoleAssignment,
    StaffMember,
    UpdateStaffRolesRequest,
)

logger = logging.getLogger(__name__)

# Single router for all /customers endpoints.
router = APIRouter(prefix="/customers", tags=["customers"])

# Invite token TTL: 7 days in seconds.
_INVITE_TOKEN_TTL = 7 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _display_name(user: User) -> str:
    """Derive a display name from the user's email (everything before ``@``).

    Falls back to the raw email when no ``@`` is present.
    """
    if user.email:
        return user.email.split("@")[0]
    # For mobile-only users we have no email, so use the mobile or a placeholder.
    return user.mobile or str(user.id)


def _staff_member(user: User, role_assignments: list[RoleAssignment]) -> StaffMember:
    """Build a :class:`StaffMember` response from a User ORM row + roles."""
    return StaffMember(
        user_id=user.id,
        email=user.email,
        name=_display_name(user),
        mobile=user.mobile,
        status=user.status,
        roles=role_assignments,
    )


def _assert_customer_access(ctx: TenantContext, customer_id: uuid.UUID) -> None:
    """Raise :class:`NotAuthorizedError` when the caller cannot access the customer.

    Superadmin passes unconditionally. For all other roles, the ``customer_id``
    must be within the caller's ``customer_scope``.
    """
    if ctx.is_superadmin:
        return
    if customer_id not in ctx.customer_scope:
        raise NotAuthorizedError(
            details={"customer_id": str(customer_id)},
        )


async def _load_roles_for_users(
    session: AsyncSession,
    user_ids: list[uuid.UUID],
    customer_id: uuid.UUID,
) -> dict[uuid.UUID, list[RoleAssignment]]:
    """Load all custom-role assignments for ``user_ids`` within ``customer_id``.

    Returns a mapping from ``user_id`` → list of :class:`RoleAssignment`.
    """
    if not user_ids:
        return {}

    stmt = (
        select(UserRole.user_id, Role.id, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.user_id.in_(user_ids),
            UserRole.customer_id == customer_id,
            Role.is_custom.is_(True),
        )
    )
    rows = (await session.execute(stmt)).all()
    result: dict[uuid.UUID, list[RoleAssignment]] = {uid: [] for uid in user_ids}
    for row in rows:
        result[row.user_id].append(
            RoleAssignment(role_id=row[1], role_name=row[2] or "")
        )
    return result


async def _validate_custom_roles(
    session: AsyncSession,
    role_ids: list[uuid.UUID],
    customer_id: uuid.UUID,
) -> None:
    """Validate that every role_id is a custom role belonging to customer_id.

    Raises :class:`NotAuthorizedError` for any role_id that is not a valid
    custom role scoped to the given customer.
    """
    if not role_ids:
        return
    stmt = select(Role.id).where(
        Role.id.in_(role_ids),
        Role.is_custom.is_(True),
        Role.customer_id == customer_id,
    )
    valid_ids = set((await session.execute(stmt)).scalars().all())
    invalid = [rid for rid in role_ids if rid not in valid_ids]
    if invalid:
        raise NotAuthorizedError(
            details={"invalid_role_ids": [str(r) for r in invalid]},
        )


# ---------------------------------------------------------------------------
# GET /customers/me
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=list[CustomerSummary],
    status_code=status.HTTP_200_OK,
    summary="List customers the authenticated user manages",
)
async def list_my_customers(
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> list[CustomerSummary]:
    """Return all customers accessible to the authenticated user (Req 4.3).

    Role-based resolution:
    * **superadmin** — all customers, ordered by name.
    * **agencyadmin** — customers belonging to their agency, ordered by name.
    * **customeradmin** — customers the user is explicitly assigned to via
      ``customer_users``, ordered by name.
    """
    if ctx.is_superadmin:
        stmt = select(Customer).order_by(Customer.name)
        rows = (await session.execute(stmt)).scalars().all()
    elif ctx.role_type == "agencyadmin" and ctx.agency_scope is not None:
        stmt = (
            select(Customer)
            .where(Customer.agency_id == ctx.agency_scope)
            .order_by(Customer.name)
        )
        rows = (await session.execute(stmt)).scalars().all()
    else:
        # customeradmin: load via customer_users join
        stmt = (
            select(Customer)
            .join(CustomerUser, CustomerUser.customer_id == Customer.id)
            .where(CustomerUser.user_id == ctx.user_id)
            .order_by(Customer.name)
        )
        rows = (await session.execute(stmt)).scalars().all()

    return [
        CustomerSummary(
            id=c.id,
            name=c.name,
            status=c.status,
            agency_id=c.agency_id,
        )
        for c in rows
    ]


# ---------------------------------------------------------------------------
# GET /customers/{customer_id}/users
# ---------------------------------------------------------------------------


@router.get(
    "/{customer_id}/users",
    response_model=list[StaffMember],
    status_code=status.HTTP_200_OK,
    summary="List staff members for a customer",
)
async def list_staff(
    customer_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> list[StaffMember]:
    """Return all users associated with the given customer (Req 4.5).

    Each staff member includes their custom-role assignments scoped to this
    customer. Fixed roles are not included in the role list.

    Errors:
    - ``NotAuthorizedError`` → 403 when the caller cannot access customer_id.
    """
    _assert_customer_access(ctx, customer_id)

    # Load all users for this customer via the association table.
    stmt = (
        select(User)
        .join(CustomerUser, CustomerUser.user_id == User.id)
        .where(CustomerUser.customer_id == customer_id)
    )
    users = list((await session.execute(stmt)).scalars().all())
    user_ids = [u.id for u in users]

    roles_by_user = await _load_roles_for_users(session, user_ids, customer_id)
    return [_staff_member(u, roles_by_user.get(u.id, [])) for u in users]


# ---------------------------------------------------------------------------
# POST /customers/{customer_id}/users
# ---------------------------------------------------------------------------


@router.post(
    "/{customer_id}/users",
    response_model=StaffMember,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a staff member to a customer",
)
async def invite_staff(
    customer_id: uuid.UUID,
    payload: InviteStaffRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> StaffMember:
    """Invite a new or existing user as a staff member of the customer.

    Logic:
    1. Verify caller access to ``customer_id``.
    2. Look up the email in ``users``.
       * If found and already in this customer → 409 ``user_already_in_customer``.
       * If found but not in this customer → add the ``CustomerUser`` row.
       * If not found → create a new ``User`` (status ``invited``) and then the
         ``CustomerUser`` row.
    3. Validate and assign any provided ``role_ids``.
    4. Generate an invite token, store it in Redis (7-day TTL), and in
       development mode print the invite link to stdout.
    5. Return the new ``StaffMember`` (201 Created).

    Errors:
    - ``NotAuthorizedError`` → 403 for invalid role_ids or missing customer access.
    - ``UserAlreadyInCustomerError`` → 409 when the email already belongs to this
      customer.
    """
    _assert_customer_access(ctx, customer_id)

    # 1. Look up the user by email.
    user_stmt = select(User).where(User.email == payload.email)
    user: User | None = (await session.execute(user_stmt)).scalar_one_or_none()

    if user is not None:
        # Check whether this user is already in the customer.
        cu_stmt = select(CustomerUser).where(
            CustomerUser.user_id == user.id,
            CustomerUser.customer_id == customer_id,
        )
        existing_cu: CustomerUser | None = (
            await session.execute(cu_stmt)
        ).scalar_one_or_none()
        if existing_cu is not None:
            raise UserAlreadyInCustomerError(
                details={
                    "email": payload.email,
                    "customer_id": str(customer_id),
                }
            )
        # User exists but is not in this customer yet — just add them.
    else:
        # Create a new invited user.
        user = User(
            email=payload.email,
            role_type="customeradmin",
            status="invited",
            password_hash=None,
        )
        session.add(user)
        # Flush to obtain the generated UUID before we reference user.id below.
        await session.flush()

    # 2. Create the CustomerUser association.
    cu = CustomerUser(user_id=user.id, customer_id=customer_id)
    session.add(cu)

    # 3. Validate and assign roles.
    if payload.role_ids:
        await _validate_custom_roles(session, payload.role_ids, customer_id)
        for role_id in payload.role_ids:
            session.add(
                UserRole(
                    user_id=user.id,
                    role_id=role_id,
                    customer_id=customer_id,
                )
            )

    await session.commit()
    await session.refresh(user)

    # 4. Generate invite token and store in Redis.
    token = secrets.token_urlsafe(32)
    redis = get_redis()
    await redis.setex(f"invite:{token}", _INVITE_TOKEN_TTL, str(user.id))

    if settings.is_development:
        invite_url = f"http://localhost:4300/accept-invite?token={token}"
        print(f"[DEV] Invite link for {payload.email}: {invite_url}")  # noqa: T201
        logger.info("Invite token for %s: %s", payload.email, token)

    # 5. Build the response.
    roles_by_user = await _load_roles_for_users(session, [user.id], customer_id)
    return _staff_member(user, roles_by_user.get(user.id, []))


# ---------------------------------------------------------------------------
# DELETE /customers/{customer_id}/users/{user_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{customer_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a staff member from a customer",
)
async def remove_staff(
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Remove a user from the customer and delete their role assignments.

    Deletes the ``CustomerUser`` row and all ``UserRole`` rows for the
    (user, customer) pair. Returns ``204 No Content``.

    Errors:
    - ``NotAuthorizedError`` → 403 when the caller cannot access customer_id.
    """
    _assert_customer_access(ctx, customer_id)

    # Delete all UserRole rows for this (user, customer).
    await session.execute(
        delete(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.customer_id == customer_id,
        )
    )

    # Delete the CustomerUser row.
    await session.execute(
        delete(CustomerUser).where(
            CustomerUser.user_id == user_id,
            CustomerUser.customer_id == customer_id,
        )
    )

    await session.commit()


# ---------------------------------------------------------------------------
# PUT /customers/{customer_id}/users/{user_id}/roles
# ---------------------------------------------------------------------------


@router.put(
    "/{customer_id}/users/{user_id}/roles",
    response_model=StaffMember,
    status_code=status.HTTP_200_OK,
    summary="Replace a staff member's role assignments",
)
async def update_staff_roles(
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: UpdateStaffRolesRequest,
    ctx: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> StaffMember:
    """Replace the user's custom-role assignments within the customer.

    Validates each ``role_id`` as a custom role belonging to ``customer_id``,
    deletes all existing ``UserRole`` rows, then inserts the new set. Returns
    the updated ``StaffMember``.

    Errors:
    - ``NotAuthorizedError`` → 403 for invalid role_ids or missing customer access.
    """
    _assert_customer_access(ctx, customer_id)

    # Validate all requested role_ids before touching rows.
    if payload.role_ids:
        await _validate_custom_roles(session, payload.role_ids, customer_id)

    # Replace the role set atomically.
    await session.execute(
        delete(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.customer_id == customer_id,
        )
    )
    for role_id in payload.role_ids:
        session.add(
            UserRole(
                user_id=user_id,
                role_id=role_id,
                customer_id=customer_id,
            )
        )

    await session.commit()

    # Load the user and build the response.
    user: User | None = await session.get(User, user_id)
    if user is None:
        raise NotAuthorizedError(details={"user_id": str(user_id)})

    roles_by_user = await _load_roles_for_users(session, [user_id], customer_id)
    return _staff_member(user, roles_by_user.get(user_id, []))


__all__ = ["router"]

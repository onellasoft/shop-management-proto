"""Module catalog and subscription router (``/modules``).

Exposes the module catalog and subscription management endpoints (Task 10.3):

* ``GET /modules/catalog?customer_id=<uuid>`` — every :class:`Module` together
  with the Customer's subscription state so the frontend can render
  unsubscribed/expired Modules as *locked* with an upgrade prompt (Req 8.3).
* ``POST /modules/subscriptions`` — add/activate a subscription for a
  (Customer, Module) pair, making the Module usable immediately (Req 8.4).
* ``DELETE /modules/subscriptions`` — remove/deactivate a subscription, making
  the Module non-usable on every subsequent request (Req 8.5).

Subscription state is derived per request from ``customer_subscriptions``.
Whether a Module is *usable* (subscribed, active, unexpired) is computed by
:meth:`AuthorizationService.is_module_usable`, so the catalog's ``usable`` flag
matches exactly what the enforcement layer will allow.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.permission import Module
from app.models.subscription import CustomerSubscription
from app.schemas.modules import (
    ModuleCatalogItem,
    ModuleCatalogResponse,
    SubscriptionRemoveRequest,
    SubscriptionRequest,
    SubscriptionResponse,
)
from app.services.authorization_service import AuthorizationService

# Single shared router for all /modules endpoints.
router = APIRouter(prefix="/modules", tags=["modules"])


def _is_usable(
    status_value: str | None,
    expires_at: datetime.datetime | None,
    *,
    now: datetime.datetime,
) -> bool:
    """Return whether a subscription is usable (active, unexpired).

    Mirrors :meth:`AuthorizationService.is_module_usable`: a subscription is
    usable when ``status == 'active'`` and it is unexpired (``expires_at`` NULL
    means "no expiry"). A naive stored timestamp is normalized to UTC so the
    comparison against the timezone-aware clock never raises.
    """
    if status_value != "active":
        return False
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
    return expires_at > now


@router.get(
    "/catalog",
    response_model=ModuleCatalogResponse,
    status_code=status.HTTP_200_OK,
    summary="Module catalog with per-customer subscription state",
)
async def get_module_catalog(
    customer_id: UUID = Query(..., description="The Customer to report state for."),
    session: AsyncSession = Depends(get_db),
) -> ModuleCatalogResponse:
    """Return every Module with ``customer_id``'s subscription state (Req 8.3).

    Each entry reports whether the Customer is ``subscribed`` to the Module, the
    subscription ``status`` and ``expires_at`` (or ``None`` when absent), and
    whether the Module is currently ``usable``. Unsubscribed or expired Modules
    come back with ``usable=False`` so the frontend can present them as locked
    with an upgrade prompt, while still listing every Module in the catalog.
    """
    # Load every Module once, then join in the Customer's subscription state.
    modules = (
        (await session.execute(select(Module).order_by(Module.key)))
        .scalars()
        .all()
    )

    subs = (
        (
            await session.execute(
                select(CustomerSubscription).where(
                    CustomerSubscription.customer_id == customer_id
                )
            )
        )
        .scalars()
        .all()
    )
    subs_by_module = {sub.module_id: sub for sub in subs}

    now = datetime.datetime.now(datetime.timezone.utc)
    items: list[ModuleCatalogItem] = []
    for module in modules:
        sub = subs_by_module.get(module.id)
        if sub is None:
            items.append(
                ModuleCatalogItem(
                    module_id=module.id,
                    key=module.key,
                    name=module.name,
                    subscribed=False,
                    status=None,
                    expires_at=None,
                    usable=False,
                )
            )
        else:
            items.append(
                ModuleCatalogItem(
                    module_id=module.id,
                    key=module.key,
                    name=module.name,
                    subscribed=True,
                    status=sub.status,
                    expires_at=sub.expires_at,
                    usable=_is_usable(sub.status, sub.expires_at, now=now),
                )
            )

    return ModuleCatalogResponse(customer_id=customer_id, modules=items)


@router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Add or activate a Customer's Module subscription",
)
async def add_subscription(
    payload: SubscriptionRequest,
    session: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    """Subscribe ``customer_id`` to ``module_id`` (Req 8.4).

    Creates a new active subscription, or re-activates and updates the expiry of
    an existing (possibly removed/expired) subscription for the (Customer,
    Module) pair. Because the ``unique(customer_id, module_id)`` constraint
    allows at most one row per pair, an existing row is updated in place rather
    than duplicated. The Module becomes usable on the next request whenever the
    resulting subscription is active and unexpired.
    """
    existing = (
        await session.execute(
            select(CustomerSubscription).where(
                CustomerSubscription.customer_id == payload.customer_id,
                CustomerSubscription.module_id == payload.module_id,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        sub = CustomerSubscription(
            customer_id=payload.customer_id,
            module_id=payload.module_id,
            status="active",
            expires_at=payload.expires_at,
        )
        session.add(sub)
    else:
        existing.status = "active"
        existing.expires_at = payload.expires_at
        sub = existing

    await session.flush()

    auth = AuthorizationService(session)
    usable = await auth.is_module_usable(payload.customer_id, payload.module_id)

    return SubscriptionResponse(
        customer_id=sub.customer_id,
        module_id=sub.module_id,
        status=sub.status,
        expires_at=sub.expires_at,
        usable=usable,
    )


@router.delete(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove or deactivate a Customer's Module subscription",
)
async def remove_subscription(
    payload: SubscriptionRemoveRequest,
    session: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    """Unsubscribe ``customer_id`` from ``module_id`` (Req 8.5).

    Deactivates the subscription by setting its status to ``removed`` so the
    Module's SubModules, Resources, and Actions become non-usable on every
    subsequent request — including requests made within Access_Token sessions
    active before the removal. The row is retained (rather than deleted) so a
    later re-subscribe can restore it; deactivating a non-existent subscription
    is a no-op that reports the not-subscribed/unusable state.
    """
    existing = (
        await session.execute(
            select(CustomerSubscription).where(
                CustomerSubscription.customer_id == payload.customer_id,
                CustomerSubscription.module_id == payload.module_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.status = "removed"
        await session.flush()
        current_status = existing.status
        current_expires = existing.expires_at
    else:
        # No subscription to remove: report the resulting not-subscribed state.
        current_status = "removed"
        current_expires = None

    return SubscriptionResponse(
        customer_id=payload.customer_id,
        module_id=payload.module_id,
        status=current_status,
        expires_at=current_expires,
        usable=False,
    )


__all__ = ["router"]

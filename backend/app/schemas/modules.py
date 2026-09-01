"""Pydantic v2 request/response schemas for the module catalog endpoints.

Backs the ``/modules/*`` router (Task 10.3). The catalog lets the frontend
render every Module together with a Customer's subscription state so
unsubscribed Modules can be shown as *locked* with an upgrade prompt (Req 8.3),
while the subscription add/remove payloads drive the subscribe/unsubscribe
endpoints.

Subscription state
------------------
For each Module the catalog reports:

* ``subscribed`` — a subscription row exists for the (Customer, Module) pair.
* ``status`` — the subscription's status (e.g. ``"active"``) or ``None`` when
  no subscription exists.
* ``expires_at`` — the subscription expiry, or ``None`` for "no expiry"/absent.
* ``usable`` — whether the Module is *usable* right now, i.e. subscribed with
  ``status == 'active'`` and unexpired. Mirrors
  :meth:`AuthorizationService.is_module_usable`. When ``usable`` is ``False``
  the frontend renders the Module as locked.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ModuleCatalogItem(BaseModel):
    """A single Module plus the Customer's subscription state (Req 8.3).

    ``subscribed``/``usable`` let the frontend distinguish "locked because never
    subscribed" from "locked because expired/inactive": ``subscribed`` is
    ``True`` with ``usable`` ``False`` when a subscription exists but is expired
    or inactive.
    """

    model_config = ConfigDict(from_attributes=True)

    module_id: uuid.UUID = Field(..., description="The Module's unique id.")
    key: str = Field(..., description="The Module's globally unique machine key.")
    name: str = Field(..., description="The Module's human-readable display name.")
    subscribed: bool = Field(
        ...,
        description="Whether a subscription row exists for this (customer, module).",
    )
    status: str | None = Field(
        default=None,
        description="The subscription status, or null when not subscribed.",
    )
    expires_at: datetime.datetime | None = Field(
        default=None,
        description="Subscription expiry; null means no expiry or not subscribed.",
    )
    usable: bool = Field(
        ...,
        description=(
            "Whether the module is usable now (subscribed, active, unexpired). "
            "When false the frontend shows the module as locked."
        ),
    )


class ModuleCatalogResponse(BaseModel):
    """The full module catalog for a Customer (Req 8.3)."""

    customer_id: uuid.UUID = Field(..., description="The Customer the catalog is for.")
    modules: list[ModuleCatalogItem] = Field(
        default_factory=list,
        description="Every Module with the Customer's subscription state.",
    )


class SubscriptionRequest(BaseModel):
    """Add/activate a subscription payload for ``POST /modules/subscriptions``.

    Subscribing a Module makes its SubModules, Resources, and Actions usable for
    the Customer immediately (Req 8.4). ``expires_at`` is optional; ``None``
    means the subscription never expires.
    """

    customer_id: uuid.UUID = Field(..., description="The Customer to subscribe.")
    module_id: uuid.UUID = Field(..., description="The Module to subscribe to.")
    expires_at: datetime.datetime | None = Field(
        default=None,
        description="Optional expiry; null means the subscription never expires.",
    )


class SubscriptionRemoveRequest(BaseModel):
    """Remove/deactivate a subscription payload.

    Unsubscribing makes the Module's SubModules, Resources, and Actions
    non-usable on every subsequent request (Req 8.5).
    """

    customer_id: uuid.UUID = Field(..., description="The Customer to unsubscribe.")
    module_id: uuid.UUID = Field(..., description="The Module to unsubscribe from.")


class SubscriptionResponse(BaseModel):
    """The current state of a single subscription after add/remove."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID = Field(..., description="The subscribed Customer.")
    module_id: uuid.UUID = Field(..., description="The subscribed Module.")
    status: str = Field(..., description="The subscription status.")
    expires_at: datetime.datetime | None = Field(
        default=None,
        description="Subscription expiry; null means no expiry.",
    )
    usable: bool = Field(
        ..., description="Whether the module is usable now (active, unexpired)."
    )


__all__ = [
    "ModuleCatalogItem",
    "ModuleCatalogResponse",
    "SubscriptionRequest",
    "SubscriptionRemoveRequest",
    "SubscriptionResponse",
]

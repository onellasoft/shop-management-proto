"""Pydantic v2 request/response schemas for the impersonation endpoints.

Backs the ``/impersonation/*`` router (Task 17.3). The schemas describe the
lifecycle payloads the frontend uses to start, end, and inspect an
impersonation session (Req 11.4, 11.5) while the target-access rules and the
single-active-session invariant are enforced by
:class:`~app.services.impersonation_service.ImpersonationService` (Req 11.1-11.3,
11.6).

The response body reuses the shape produced by
:meth:`ImpersonationService.build_indicator` — the same indicator the middleware
(Task 18) attaches to every response — so the frontend has a single, consistent
representation of "who am I impersonating" whether it reads it from a lifecycle
response or from a per-request header.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, Field, model_validator


class ImpersonationStartRequest(BaseModel):
    """Start-impersonation payload for ``POST /impersonation/start`` (Req 11.4).

    Carries exactly one target: either ``agency_id`` or ``customer_id``. The XOR
    is validated here so an obviously malformed request (neither or both) is
    rejected before the service is called; the service re-checks the same
    invariant (mirroring the model's XOR CHECK) as defense in depth.
    """

    agency_id: uuid.UUID | None = Field(
        default=None,
        description="The Agency to impersonate. Mutually exclusive with customer_id.",
    )
    customer_id: uuid.UUID | None = Field(
        default=None,
        description="The Customer to impersonate. Mutually exclusive with agency_id.",
    )

    @model_validator(mode="after")
    def _exactly_one_target(self) -> ImpersonationStartRequest:
        """Require precisely one of ``agency_id`` / ``customer_id`` (Req 11.4)."""
        if (self.agency_id is None) == (self.customer_id is None):
            raise ValueError(
                "Exactly one of agency_id or customer_id must be provided."
            )
        return self


class ImpersonationEndRequest(BaseModel):
    """End-impersonation payload for ``POST /impersonation/end`` (Req 11.5).

    The body may be empty. ``session_id`` is optional and advisory: the endpoint
    ends the acting impersonator's *current* active session regardless (looked
    up via :meth:`ImpersonationService.get_active`), so a stale or omitted id
    never ends the wrong session.
    """

    session_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional id of the session to end. Advisory only; the current "
            "active session for the acting user is ended regardless."
        ),
    )


class ImpersonationIndicator(BaseModel):
    """The impersonation indicator describing the active session (Req 11.4).

    Mirrors :meth:`ImpersonationService.build_indicator`. When there is no
    active session, ``impersonating`` is ``False`` and the remaining fields are
    ``None`` (see :meth:`ImpersonationIndicator.inactive`).
    """

    impersonating: bool = Field(
        ...,
        description="Whether an impersonation session is currently active.",
    )
    impersonated_type: str | None = Field(
        default=None,
        description="The impersonated entity type: 'customer' or 'agency'.",
    )
    impersonated_id: uuid.UUID | None = Field(
        default=None,
        description="The impersonated entity's id, or null when not impersonating.",
    )
    session_id: uuid.UUID | None = Field(
        default=None,
        description="The active session's id, or null when not impersonating.",
    )
    started_at: datetime.datetime | None = Field(
        default=None,
        description="When the session started, or null when not impersonating.",
    )

    @classmethod
    def inactive(cls) -> ImpersonationIndicator:
        """Return the "not impersonating" indicator (``impersonating=False``)."""
        return cls(impersonating=False)


__all__ = [
    "ImpersonationStartRequest",
    "ImpersonationEndRequest",
    "ImpersonationIndicator",
]

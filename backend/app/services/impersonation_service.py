"""Impersonation_Service — impersonation session lifecycle (Task 17.2).

Implements starting, ending, and looking up impersonation sessions for a
superadmin or agencyadmin (Requirement 11). The service owns the *lifecycle*
of an :class:`ImpersonationSession` row; the tenant-boundary enforcement that
runs on every subsequent request (Req 12) is wired separately in Task 18.

Design reference: "Components and Interfaces → Impersonation_Service" and
"Impersonation Mechanism (End to End)"::

    async def start(self, impersonator, agency_id, customer_id) -> ImpersonationSession
    async def end(self, session_id) -> None
    async def get_active(self, impersonator_id) -> ImpersonationSession | None
    def build_indicator(self, session) -> dict

Lifecycle semantics
--------------------
* **Target validation** (Req 11.1-11.3): a superadmin may impersonate *any*
  Agency or *any* Customer; an agencyadmin may impersonate *only* a Customer
  within its accessible-customer scope (resolved via
  :meth:`AuthorizationService.resolve_agency_customer_ids`, cache-backed). An
  agencyadmin targeting an Agency, or a Customer outside its scope, is rejected
  with :class:`ImpersonationForbiddenError`.
* **Exactly one target** (mirrors the model XOR CHECK): precisely one of
  ``agency_id`` / ``customer_id`` must be supplied; neither/both raises
  :class:`ValidationError`.
* **Record on start** (Req 11.4): a row is inserted with the impersonator, the
  target, ``active=True`` and ``started_at`` taken from the injectable clock so
  the 60-minute expiry is deterministic in tests.
* **Single active session** (Req 11.6): if the impersonator already holds a
  *fresh* active session, a new ``start`` is rejected with
  :class:`ImpersonationActiveError`. The DB partial-unique index enforces the
  same invariant; an :class:`IntegrityError` from a concurrent insert is caught
  and surfaced as the same error (mirroring ``create_custom_role``).
* **End** (Req 11.5): ``ended_at`` is stamped and ``active`` set ``False``.
* **Expiry** (Req 11.7): :meth:`get_active` returns the active session only
  while it is younger than the configured max age (60 min); a session older
  than that is treated as expired — it is marked ended/inactive and ``None`` is
  returned so the impersonator's own context is enforced again.
* **No re-auth / no IP/device gate** (Req 11.8): ``start``/``end`` simply
  operate; no authentication re-check or IP/device restriction is applied.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import (
    ImpersonationActiveError,
    ImpersonationForbiddenError,
    ValidationError,
)
from app.models.impersonation import ImpersonationSession
from app.models.user import User
from app.services.authorization_service import AuthorizationService

# Max age of an impersonation session before it is treated as expired (Req 11.7).
# Sourced from configuration (mirroring the OTP TTL convention) so it is tunable
# per deployment; defaults to 60 minutes.
IMPERSONATION_SESSION_MAX_AGE = datetime.timedelta(
    minutes=settings.impersonation_session_ttl_minutes
)


def _utcnow() -> datetime.datetime:
    """Return the current timezone-aware UTC time (default module clock)."""
    return datetime.datetime.now(datetime.timezone.utc)


class ImpersonationService:
    """Manage the lifecycle of impersonation sessions (Req 11).

    Instantiated per request with the active :class:`AsyncSession`. Target-scope
    validation for an agencyadmin reuses :class:`AuthorizationService` (its
    cache-backed :meth:`resolve_agency_customer_ids`); an instance may be
    injected (tests) or is constructed lazily against the same session.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime.datetime] | None = None,
        authorization_service: AuthorizationService | None = None,
        max_age: datetime.timedelta | None = None,
    ) -> None:
        self._session = session
        # Injectable clock for the 60-minute expiry check (Req 11.7). Defaults
        # to real UTC time; tests supply a fake clock.
        self._now = now if now is not None else _utcnow
        # AuthorizationService supplies the agencyadmin accessible-customer
        # scope (cache-backed). Share the same session so the resolution reads
        # the same transaction; tests may inject a fake.
        self._authz = authorization_service
        # Allow tests to override the max age directly; otherwise the module
        # constant (config-driven) applies.
        self._max_age = (
            max_age if max_age is not None else IMPERSONATION_SESSION_MAX_AGE
        )

    def _get_authorization_service(self) -> AuthorizationService:
        """Return the AuthorizationService, constructing the default lazily.

        Only built when an agencyadmin scope must be resolved so a superadmin
        start (which needs no scope check) never constructs one.
        """
        if self._authz is None:
            self._authz = AuthorizationService(self._session, now=self._now)
        return self._authz

    async def start(
        self,
        impersonator: User,
        agency_id: UUID | None = None,
        customer_id: UUID | None = None,
    ) -> ImpersonationSession:
        """Start an impersonation session for ``impersonator`` (Req 11.1-11.6).

        Validates that exactly one target is supplied and that the impersonator
        is permitted to impersonate it, rejects a second concurrent session,
        then inserts an active :class:`ImpersonationSession` recording the
        impersonator, the target, and ``started_at`` (Req 11.4).

        Parameters
        ----------
        impersonator:
            The acting :class:`User` (superadmin or agencyadmin).
        agency_id:
            The Agency to impersonate, or ``None``. Mutually exclusive with
            ``customer_id``.
        customer_id:
            The Customer to impersonate, or ``None``. Mutually exclusive with
            ``agency_id``.

        Returns
        -------
        ImpersonationSession
            The persisted, flushed session (its ``id`` is populated).

        Raises
        ------
        ValidationError
            When neither or both of ``agency_id`` / ``customer_id`` are given.
        ImpersonationForbiddenError
            When the impersonator may not impersonate the requested target
            (Req 11.3).
        ImpersonationActiveError
            When the impersonator already holds a fresh active session
            (Req 11.6).
        """
        # Exactly one target (mirror the model XOR CHECK). Reject neither/both.
        if (agency_id is None) == (customer_id is None):
            raise ValidationError(
                "Exactly one of agency_id or customer_id must be provided.",
                details={
                    "agency_id": str(agency_id) if agency_id else None,
                    "customer_id": str(customer_id) if customer_id else None,
                },
            )

        # Req 11.1-11.3 — validate the impersonator can reach the target.
        await self._assert_can_impersonate(impersonator, agency_id, customer_id)

        # Req 11.6 — reject a second active session. Checking the fresh active
        # session first gives a clear error before hitting the DB unique index.
        if await self.get_active(impersonator.id) is not None:
            raise ImpersonationActiveError(
                details={"impersonator_user_id": str(impersonator.id)},
            )

        # Req 11.4 — record the session with the injectable clock's timestamp.
        session_row = ImpersonationSession(
            impersonator_user_id=impersonator.id,
            impersonated_agency_id=agency_id,
            impersonated_customer_id=customer_id,
            active=True,
            started_at=self._now(),
        )
        self._session.add(session_row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # The partial-unique index (active per impersonator) may reject a
            # concurrent second start; surface it as the same domain error
            # rather than a 500 (mirrors create_custom_role's handling).
            await self._session.rollback()
            raise ImpersonationActiveError(
                details={"impersonator_user_id": str(impersonator.id)},
            ) from exc
        return session_row

    async def _assert_can_impersonate(
        self,
        impersonator: User,
        agency_id: UUID | None,
        customer_id: UUID | None,
    ) -> None:
        """Enforce impersonation target access (Req 11.1-11.3).

        * **superadmin** — may impersonate any Agency or any Customer (Req 11.1).
        * **agencyadmin** — may impersonate only a Customer within its
          accessible-customer scope; targeting an Agency, or a Customer outside
          its scope, is forbidden (Req 11.2, 11.3).
        * any other role_type is not permitted to impersonate.

        Raises
        ------
        ImpersonationForbiddenError
            When the target is outside the impersonator's scope (Req 11.3).
        """
        role_type = impersonator.role_type

        # Req 11.1 — a superadmin has no tenant boundary: any target is allowed.
        if role_type == "superadmin":
            return

        if role_type == "agencyadmin":
            # Req 11.2/11.3 — an agencyadmin may only impersonate a Customer
            # (never an Agency) and only one within its accessible scope.
            if agency_id is not None:
                raise ImpersonationForbiddenError(
                    details={
                        "reason": "agencyadmin_cannot_impersonate_agency",
                        "impersonated_agency_id": str(agency_id),
                    },
                )
            if impersonator.agency_id is None:
                # No agency → no derivable scope → nothing is impersonable.
                raise ImpersonationForbiddenError(
                    details={"reason": "agencyadmin_missing_agency"},
                )
            authz = self._get_authorization_service()
            accessible = await authz.resolve_agency_customer_ids(
                impersonator.agency_id
            )
            if customer_id not in set(accessible):
                raise ImpersonationForbiddenError(
                    details={
                        "reason": "customer_outside_agency_scope",
                        "impersonated_customer_id": str(customer_id),
                    },
                )
            return

        # superadmin/agencyadmin are the only roles permitted to impersonate.
        raise ImpersonationForbiddenError(
            details={"reason": "role_cannot_impersonate", "role_type": role_type},
        )

    async def end(self, session_id: UUID) -> None:
        """End an impersonation session (Req 11.5).

        Stamps ``ended_at`` with the injectable clock and marks the session
        inactive. A missing or already-ended session is a no-op so ``end`` is
        idempotent.

        Parameters
        ----------
        session_id:
            The id of the session to end.
        """
        session_row = await self._session.get(ImpersonationSession, session_id)
        if session_row is None:
            return
        if session_row.active:
            session_row.active = False
        # Only stamp ended_at once so re-ending doesn't overwrite the original
        # end time.
        if session_row.ended_at is None:
            session_row.ended_at = self._now()
        await self._session.flush()

    async def get_active(
        self, impersonator_id: UUID
    ) -> ImpersonationSession | None:
        """Return the impersonator's fresh active session, else ``None`` (Req 11.7).

        Loads the single ``active=True`` session for ``impersonator_id`` (at most
        one exists per the partial-unique index) and applies the 60-minute
        expiry against the injectable clock: a session whose ``started_at`` is
        older than :data:`IMPERSONATION_SESSION_MAX_AGE` is treated as expired.
        An expired session is marked ended/inactive (so it doesn't linger and
        the impersonator's own context resumes) and ``None`` is returned.

        Parameters
        ----------
        impersonator_id:
            The impersonator whose active session to look up.

        Returns
        -------
        ImpersonationSession | None
            The active, unexpired session, or ``None`` when there is none or the
            existing one has expired.
        """
        stmt = select(ImpersonationSession).where(
            ImpersonationSession.impersonator_user_id == impersonator_id,
            ImpersonationSession.active.is_(True),
        )
        session_row = (
            await self._session.execute(stmt)
        ).scalar_one_or_none()
        if session_row is None:
            return None

        started_at = session_row.started_at
        # Normalize a naive stored timestamp to UTC so the comparison against
        # the timezone-aware clock never raises.
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=datetime.timezone.utc)

        if self._now() - started_at > self._max_age:
            # Req 11.7 — an active-but-expired session is treated as ended so
            # the impersonator's own tenant context is enforced again.
            session_row.active = False
            if session_row.ended_at is None:
                session_row.ended_at = self._now()
            await self._session.flush()
            return None

        return session_row

    def build_indicator(self, session: ImpersonationSession) -> dict:
        """Build the impersonation indicator for the frontend banner (Req 12.3).

        Returns a small, serializable dict identifying the impersonated entity
        so the middleware (Task 18) can attach it to each response and the
        frontend can render the banner + exit control.

        Parameters
        ----------
        session:
            The active impersonation session to describe.

        Returns
        -------
        dict
            ``{"impersonating": True, "impersonated_type": "customer"|"agency",
            "impersonated_id": "<uuid>", "started_at": "<iso8601>"}``.
        """
        if session.impersonated_customer_id is not None:
            impersonated_type = "customer"
            impersonated_id = session.impersonated_customer_id
        else:
            impersonated_type = "agency"
            impersonated_id = session.impersonated_agency_id

        started_at = session.started_at
        return {
            "impersonating": True,
            "impersonated_type": impersonated_type,
            "impersonated_id": str(impersonated_id),
            "started_at": started_at.isoformat() if started_at is not None else None,
        }


__all__ = ["ImpersonationService", "IMPERSONATION_SESSION_MAX_AGE"]

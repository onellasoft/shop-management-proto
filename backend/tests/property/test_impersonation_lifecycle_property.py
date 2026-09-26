"""Property-based tests for the impersonation session lifecycle.

# Feature: onella-backend, Property 22: Impersonation start authorization and single active session

**Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.6**

# Feature: onella-backend, Property 24: Impersonation end and expiry restore the impersonator context

**Validates: Requirements 11.5, 11.7, 12.4**

These tests exercise the REAL :class:`ImpersonationService`
(``app/services/impersonation_service.py``, Task 17.2) over
Hypothesis-generated worlds, driving its injectable clock (``now=``) and an
injected fake :class:`AuthorizationService` (``authorization_service=``) so the
agencyadmin accessible-customer scope resolves entirely in memory — no live
Redis/Postgres is touched.

* **Property 22** — for any impersonator and target: a superadmin may start
  impersonation of *any* Agency or Customer, and the started session records
  the impersonator, the impersonated entity, and the start timestamp; an
  agencyadmin may start *only* for a Customer within its accessible scope
  (an Agency target, or a Customer outside scope, is rejected with
  :class:`ImpersonationForbiddenError`); and while an impersonator already
  holds an active session any further start is rejected with
  :class:`ImpersonationActiveError`.

* **Property 24** — for any impersonation session: ending it stamps ``ended_at``
  and sets ``active=False`` (and :meth:`get_active` then returns ``None`` — the
  impersonator's own context resumes); and with no explicit end,
  :meth:`get_active` returns the session while it is younger than 60 minutes but
  ``None`` once older (expiry → own context resumes), driven across the
  60-minute boundary by the injectable clock.

The database boundary reuses the in-memory fake ``AsyncSession`` /
``AuthorizationService`` pattern established in
``tests/unit/test_impersonation_service.py`` (adapted for Hypothesis worlds and
made robust to multiple rows by assigning a primary key on ``flush``, mirroring
the ORM's Python-side ``default=uuid.uuid4``). Because the service is ``async``
and Hypothesis drives synchronous test bodies, each example runs its coroutine
to completion via ``asyncio.run`` with a FRESH fake session per example
(mirroring ``tests/property/test_tenant_context_derivation_property.py``); no
crypto or real I/O runs, so 100+ iterations stay fast.
"""

from __future__ import annotations

import asyncio
import datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.errors import (
    ImpersonationActiveError,
    ImpersonationForbiddenError,
)
from app.models.impersonation import ImpersonationSession
from app.models.user import User
from app.services.impersonation_service import ImpersonationService

UTC = datetime.timezone.utc

# The service's configured max session age (Req 11.7 → 60 minutes). Imported
# from the service so the boundary tests track the real configuration.
from app.services.impersonation_service import IMPERSONATION_SESSION_MAX_AGE


# ---------------------------------------------------------------------------
# In-memory fakes (adapted from tests/unit/test_impersonation_service.py)
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, row) -> None:  # noqa: ANN001
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """AsyncSession stand-in recording ``ImpersonationSession`` rows.

    Supports the operations the service uses: ``add``, ``flush``, ``rollback``,
    ``get`` by id, and ``execute`` of the active-session ``select``.

    ``flush`` assigns a primary key to any freshly-added row lacking one,
    mirroring the ORM's Python-side ``default=uuid.uuid4`` on
    ``ImpersonationSession.id``. This keeps ``get(model, id)`` unambiguous when a
    session accumulates more than one row across a world.
    """

    def __init__(self) -> None:
        self.rows: list[ImpersonationSession] = []
        self.rollback_called = False

    def add(self, row) -> None:  # noqa: ANN001
        self.rows.append(row)

    async def flush(self) -> None:
        for row in self.rows:
            if getattr(row, "id", None) is None:
                row.id = uuid4()

    async def rollback(self) -> None:
        self.rollback_called = True
        if self.rows:
            self.rows.pop()

    async def get(self, model, pk):  # noqa: ANN001
        for row in self.rows:
            if row.id == pk:
                return row
        return None

    async def execute(self, statement):  # noqa: ANN001
        impersonator_id, active_wanted = _extract_active_filter(statement)
        for row in self.rows:
            if (
                row.impersonator_user_id == impersonator_id
                and bool(row.active) == active_wanted
            ):
                return _Result(row)
        return _Result(None)


def _extract_active_filter(statement) -> tuple[UUID, bool]:
    """Pull the impersonator id and desired active flag from the WHERE clause."""
    impersonator_id: UUID | None = None
    active_wanted = True
    for clause in statement.whereclause.clauses:
        left = getattr(clause, "left", None)
        key = getattr(left, "key", None)
        if key == "impersonator_user_id":
            impersonator_id = getattr(clause.right, "value", clause.right)
        elif key == "active":
            active_wanted = bool(getattr(clause.right, "value", True))
    assert impersonator_id is not None
    return impersonator_id, active_wanted


class _FakeAuthorizationService:
    """Fake exposing only ``resolve_agency_customer_ids`` for scope checks."""

    def __init__(self, mapping: dict[UUID, list[UUID]]) -> None:
        self._mapping = mapping

    async def resolve_agency_customer_ids(self, agency_id: UUID) -> list[UUID]:
        return list(self._mapping.get(agency_id, []))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user(role_type: str, *, agency_id: UUID | None = None) -> User:
    u = User(role_type=role_type, agency_id=agency_id)
    u.id = uuid4()
    return u


def _fixed_clock(value: datetime.datetime):
    return lambda: value


def _service(
    session: _FakeSession,
    *,
    now: datetime.datetime | None = None,
    authz: _FakeAuthorizationService | None = None,
) -> ImpersonationService:
    clock = _fixed_clock(now) if now is not None else None
    return ImpersonationService(session, now=clock, authorization_service=authz)


# Distinct UUIDs — fresh uuid4()s keep ids globally unique so scope membership
# and impersonator matching are unambiguous.
_uuids = st.builds(uuid4)


# ===========================================================================
# Property 22 — start authorization + single active session
# ===========================================================================


@st.composite
def _p22_case(draw: st.DrawFn):
    """A start-authorization world for a superadmin or agencyadmin.

    Returns a tuple ``(role, admin, agency_id, customer_id, authz, expect)``:

    * ``role`` — "superadmin" or "agencyadmin".
    * ``admin`` — the impersonating :class:`User`.
    * ``agency_id`` / ``customer_id`` — exactly one is set (the requested
      target); the other is ``None``.
    * ``authz`` — the fake AuthorizationService the agencyadmin scope resolves
      through (``None`` for superadmin).
    * ``expect`` — "ok" if the start should succeed, or "forbidden" if it
      should raise :class:`ImpersonationForbiddenError`.
    """
    role = draw(st.sampled_from(["superadmin", "agencyadmin"]))
    # A structurally-varying nonce keeps every example distinct so Hypothesis
    # spends its full example budget rather than treating the space as
    # exhausted.
    draw(st.text(min_size=0, max_size=6))

    if role == "superadmin":
        admin = _user("superadmin")
        # Superadmin may target any agency or any customer — either shape is OK.
        target_kind = draw(st.sampled_from(["agency", "customer"]))
        if target_kind == "agency":
            return ("superadmin", admin, draw(_uuids), None, None, "ok")
        return ("superadmin", admin, None, draw(_uuids), None, "ok")

    # agencyadmin — build an accessible-customer scope for its agency.
    agency = draw(_uuids)
    admin = _user("agencyadmin", agency_id=agency)
    accessible = draw(st.lists(_uuids, min_size=0, max_size=5, unique=True))
    # Noise: another agency's scope that must never grant access. Draw a
    # distinct other-agency id so its noise scope can never overwrite this
    # agency's entry in the mapping.
    other_agency = draw(_uuids.filter(lambda a: a != agency))
    other_accessible = draw(st.lists(_uuids, min_size=0, max_size=4, unique=True))
    authz = _FakeAuthorizationService(
        {agency: list(accessible), other_agency: list(other_accessible)}
    )

    target_kind = draw(st.sampled_from(["agency", "in_scope", "out_of_scope"]))
    if target_kind == "agency":
        # Targeting an Agency is forbidden for an agencyadmin (Req 11.3).
        return ("agencyadmin", admin, draw(_uuids), None, authz, "forbidden")
    if target_kind == "in_scope" and accessible:
        customer = draw(st.sampled_from(list(accessible)))
        return ("agencyadmin", admin, None, customer, authz, "ok")
    # out_of_scope (or in_scope requested with an empty scope) — a customer id
    # that is not in the accessible set is forbidden (Req 11.2/11.3).
    forbidden_customer = draw(
        _uuids.filter(lambda cid: cid not in set(accessible))
    )
    return ("agencyadmin", admin, None, forbidden_customer, authz, "forbidden")


# Feature: onella-backend, Property 22: Impersonation start authorization and single active session
@settings(max_examples=200, deadline=None)
@given(case=_p22_case())
def test_start_authorization_and_single_active_session(case) -> None:
    """Start authorization matches role scope; a second start is rejected.

    Validates Requirements 11.1, 11.2, 11.3, 11.4, 11.6.
    """
    role, admin, agency_id, customer_id, authz, expect = case
    start_time = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

    async def run() -> None:
        session = _FakeSession()  # FRESH per example.
        svc = _service(session, now=start_time, authz=authz)

        if expect == "forbidden":
            # Req 11.2/11.3 — out-of-scope customer, or agency target for an
            # agencyadmin, is rejected and no session is recorded.
            with pytest.raises(ImpersonationForbiddenError):
                await svc.start(
                    admin, agency_id=agency_id, customer_id=customer_id
                )
            assert await svc.get_active(admin.id) is None
            return

        # expect == "ok" — start succeeds and records the session (Req 11.4).
        result = await svc.start(
            admin, agency_id=agency_id, customer_id=customer_id
        )
        assert result.impersonator_user_id == admin.id  # impersonator recorded
        assert result.impersonated_agency_id == agency_id  # target recorded
        assert result.impersonated_customer_id == customer_id
        assert result.started_at == start_time  # start timestamp recorded
        assert result.active is True

        # Req 11.6 — while this session is active, a further start with a
        # target the impersonator is *authorized* for is still rejected. Reuse
        # the original (authorized) target so the active-session guard — not the
        # authorization guard, which runs first — is what rejects it.
        with pytest.raises(ImpersonationActiveError):
            await svc.start(
                admin, agency_id=agency_id, customer_id=customer_id
            )

    asyncio.run(run())


# ===========================================================================
# Property 24 — end + 60-minute expiry restore the impersonator context
# ===========================================================================


@st.composite
def _p24_end_case(draw: st.DrawFn):
    """A superadmin session started at t0, ended at t0 + delta (delta >= 0)."""
    admin = _user("superadmin")
    target_kind = draw(st.sampled_from(["agency", "customer"]))
    agency_id = draw(_uuids) if target_kind == "agency" else None
    customer_id = draw(_uuids) if target_kind == "customer" else None
    end_after = datetime.timedelta(
        minutes=draw(st.integers(min_value=0, max_value=600))
    )
    return admin, agency_id, customer_id, end_after


@st.composite
def _p24_expiry_case(draw: st.DrawFn):
    """A superadmin session read at t0 + delta straddling the 60-min boundary.

    ``delta_minutes`` is drawn across a range that covers well under, right at,
    and well beyond the 60-minute expiry so both the fresh (<= 60) and expired
    (> 60) branches are exercised.
    """
    admin = _user("superadmin")
    target_kind = draw(st.sampled_from(["agency", "customer"]))
    agency_id = draw(_uuids) if target_kind == "agency" else None
    customer_id = draw(_uuids) if target_kind == "customer" else None
    delta_minutes = draw(st.integers(min_value=0, max_value=180))
    return admin, agency_id, customer_id, delta_minutes


# Feature: onella-backend, Property 24: Impersonation end and expiry restore the impersonator context
@settings(max_examples=150, deadline=None)
@given(case=_p24_end_case())
def test_ending_session_restores_impersonator_context(case) -> None:
    """Ending a session stamps ended_at, deactivates it, and resumes own context.

    Validates Requirements 11.5, 12.4.
    """
    admin, agency_id, customer_id, end_after = case
    start_time = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    end_time = start_time + end_after

    async def run() -> None:
        session = _FakeSession()
        svc = _service(session, now=start_time)
        row = await svc.start(
            admin, agency_id=agency_id, customer_id=customer_id
        )
        assert row.active is True

        # End at end_time via a clock-advanced service instance.
        svc_end = _service(session, now=end_time)
        await svc_end.end(row.id)

        # Req 11.5 — ended_at stamped and the session marked inactive.
        assert row.active is False
        assert row.ended_at == end_time

        # Req 12.4 — after the session ends the impersonator's own context is
        # enforced again: no active session is returned on subsequent lookups.
        assert await svc_end.get_active(admin.id) is None

    asyncio.run(run())


# Feature: onella-backend, Property 24: Impersonation end and expiry restore the impersonator context
@settings(max_examples=200, deadline=None)
@given(case=_p24_expiry_case())
def test_expiry_after_60_minutes_restores_impersonator_context(case) -> None:
    """get_active returns the session iff age <= 60 min; expiry resumes own context.

    Validates Requirements 11.7, 12.4.
    """
    admin, agency_id, customer_id, delta_minutes = case
    start_time = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    read_time = start_time + datetime.timedelta(minutes=delta_minutes)
    age = read_time - start_time

    async def run() -> None:
        session = _FakeSession()
        svc = _service(session, now=start_time)
        row = await svc.start(
            admin, agency_id=agency_id, customer_id=customer_id
        )

        # Read the active session with the clock advanced by delta_minutes.
        svc_read = _service(session, now=read_time)
        active = await svc_read.get_active(admin.id)

        if age <= IMPERSONATION_SESSION_MAX_AGE:
            # Fresh (<= 60 min) — the same active session is returned.
            assert active is not None
            assert active.id == row.id
            assert active.active is True
        else:
            # Req 11.7 — expired (> 60 min): treated as ended, own context
            # resumes (Req 12.4). The row is marked inactive/ended.
            assert active is None
            assert row.active is False
            assert row.ended_at == read_time

    asyncio.run(run())

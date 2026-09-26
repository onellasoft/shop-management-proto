"""Unit tests for :class:`ImpersonationService` (Task 17.2).

Cover the impersonation session lifecycle (Req 11.1-11.8):

* **start authorization** — a superadmin may impersonate any Agency or Customer
  (Req 11.1); an agencyadmin may impersonate a Customer within its scope but is
  rejected for a Customer outside its scope or for targeting an Agency
  (Req 11.2, 11.3).
* **target shape** — neither/both target ids raise :class:`ValidationError`
  (mirrors the model XOR CHECK).
* **single active session** — starting a second session while one is active
  raises :class:`ImpersonationActiveError` (Req 11.6).
* **end** — sets ``ended_at`` and ``active=False`` (Req 11.5).
* **expiry** — :meth:`get_active` returns a fresh session but ``None`` once the
  session is older than 60 minutes, driven by the injectable clock (Req 11.7).
* **indicator** — :meth:`build_indicator` returns the expected shape for a
  customer and an agency target (Req 12.3).

The database boundary is an in-memory fake ``AsyncSession`` recording added
:class:`ImpersonationSession` rows and answering the two query shapes the
service issues: ``session.get(ImpersonationSession, id)`` and
``select(ImpersonationSession).where(impersonator_user_id == ..., active is
True)``. The agencyadmin scope resolution is a small fake AuthorizationService
so no live Redis/Postgres is required.
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest

from app.core.errors import (
    ImpersonationActiveError,
    ImpersonationForbiddenError,
    ValidationError,
)
from app.models.impersonation import ImpersonationSession
from app.models.user import User
from app.services.impersonation_service import ImpersonationService

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, row) -> None:  # noqa: ANN001
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """AsyncSession stand-in recording ``ImpersonationSession`` rows.

    Supports the operations the service uses: ``add``, ``flush``, ``rollback``,
    ``get`` by id, and ``execute`` of the active-session ``select``. An optional
    ``raise_on_flush`` simulates the DB partial-unique index rejecting a second
    active insert.
    """

    def __init__(self, *, raise_on_flush: Exception | None = None) -> None:
        self.rows: list[ImpersonationSession] = []
        self._raise_on_flush = raise_on_flush
        self.rollback_called = False

    def add(self, row) -> None:  # noqa: ANN001
        self.rows.append(row)

    async def flush(self) -> None:
        if self._raise_on_flush is not None:
            exc = self._raise_on_flush
            self._raise_on_flush = None
            raise exc

    async def rollback(self) -> None:
        self.rollback_called = True
        # Mirror a real rollback removing the pending (unflushed) insert.
        if self.rows:
            self.rows.pop()

    async def get(self, model, pk):  # noqa: ANN001
        for row in self.rows:
            if row.id == pk:
                return row
        return None

    async def execute(self, statement):  # noqa: ANN001
        # Evaluate the active-session lookup: impersonator match + active True.
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
            # ``active.is_(True)`` — the right side carries the literal.
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
    return ImpersonationService(
        session,
        now=clock,
        authorization_service=authz,
    )


# ===========================================================================
# start — superadmin may impersonate any agency or customer (Req 11.1)
# ===========================================================================


async def test_superadmin_can_start_impersonation_of_agency():
    session = _FakeSession()
    svc = _service(session)
    admin = _user("superadmin")
    agency = uuid4()

    result = await svc.start(admin, agency_id=agency)

    assert result.impersonated_agency_id == agency
    assert result.impersonated_customer_id is None
    assert result.active is True
    assert result.impersonator_user_id == admin.id
    assert result in session.rows


async def test_superadmin_can_start_impersonation_of_customer():
    session = _FakeSession()
    svc = _service(session)
    admin = _user("superadmin")
    customer = uuid4()

    result = await svc.start(admin, customer_id=customer)

    assert result.impersonated_customer_id == customer
    assert result.impersonated_agency_id is None
    assert result.active is True


# ===========================================================================
# start — agencyadmin scope (Req 11.2, 11.3)
# ===========================================================================


async def test_agencyadmin_can_impersonate_customer_in_scope():
    agency = uuid4()
    customer = uuid4()
    authz = _FakeAuthorizationService({agency: [customer]})
    session = _FakeSession()
    svc = _service(session, authz=authz)
    admin = _user("agencyadmin", agency_id=agency)

    result = await svc.start(admin, customer_id=customer)

    assert result.impersonated_customer_id == customer
    assert result.active is True


async def test_agencyadmin_rejected_for_customer_outside_scope():
    agency = uuid4()
    in_scope = uuid4()
    out_of_scope = uuid4()
    authz = _FakeAuthorizationService({agency: [in_scope]})
    session = _FakeSession()
    svc = _service(session, authz=authz)
    admin = _user("agencyadmin", agency_id=agency)

    with pytest.raises(ImpersonationForbiddenError):
        await svc.start(admin, customer_id=out_of_scope)


async def test_agencyadmin_rejected_for_targeting_agency():
    agency = uuid4()
    authz = _FakeAuthorizationService({agency: [uuid4()]})
    session = _FakeSession()
    svc = _service(session, authz=authz)
    admin = _user("agencyadmin", agency_id=agency)

    with pytest.raises(ImpersonationForbiddenError):
        await svc.start(admin, agency_id=uuid4())


async def test_customeradmin_cannot_impersonate():
    session = _FakeSession()
    svc = _service(session)
    admin = _user("customeradmin")

    with pytest.raises(ImpersonationForbiddenError):
        await svc.start(admin, customer_id=uuid4())


# ===========================================================================
# start — target shape (ValidationError)
# ===========================================================================


async def test_start_with_no_target_raises_validation_error():
    session = _FakeSession()
    svc = _service(session)
    admin = _user("superadmin")

    with pytest.raises(ValidationError):
        await svc.start(admin)


async def test_start_with_both_targets_raises_validation_error():
    session = _FakeSession()
    svc = _service(session)
    admin = _user("superadmin")

    with pytest.raises(ValidationError):
        await svc.start(admin, agency_id=uuid4(), customer_id=uuid4())


# ===========================================================================
# start — single active session (Req 11.6)
# ===========================================================================


async def test_second_start_while_active_raises_impersonation_active():
    now = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    session = _FakeSession()
    svc = _service(session, now=now)
    admin = _user("superadmin")

    await svc.start(admin, customer_id=uuid4())
    with pytest.raises(ImpersonationActiveError):
        await svc.start(admin, customer_id=uuid4())


async def test_start_surfaces_integrity_error_as_impersonation_active():
    from sqlalchemy.exc import IntegrityError

    session = _FakeSession(
        raise_on_flush=IntegrityError("dup", {}, Exception("dup"))
    )
    svc = _service(session)
    admin = _user("superadmin")

    with pytest.raises(ImpersonationActiveError):
        await svc.start(admin, customer_id=uuid4())
    assert session.rollback_called is True


# ===========================================================================
# end — sets ended_at + active=False (Req 11.5)
# ===========================================================================


async def test_end_marks_session_inactive_and_stamps_ended_at():
    start_time = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    end_time = datetime.datetime(2024, 1, 1, 12, 30, tzinfo=UTC)
    session = _FakeSession()
    svc = _service(session, now=start_time)
    admin = _user("superadmin")
    row = await svc.start(admin, customer_id=uuid4())

    # End with a later clock reading.
    svc_end = _service(session, now=end_time)
    await svc_end.end(row.id)

    assert row.active is False
    assert row.ended_at == end_time


async def test_end_missing_session_is_noop():
    session = _FakeSession()
    svc = _service(session)
    # Should not raise for an unknown id.
    await svc.end(uuid4())


# ===========================================================================
# get_active — freshness / 60-min expiry via injectable clock (Req 11.7)
# ===========================================================================


async def test_get_active_returns_fresh_session():
    start_time = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    session = _FakeSession()
    svc = _service(session, now=start_time)
    admin = _user("superadmin")
    row = await svc.start(admin, customer_id=uuid4())

    # 59 minutes later — still active.
    later = start_time + datetime.timedelta(minutes=59)
    svc_read = _service(session, now=later)
    active = await svc_read.get_active(admin.id)

    assert active is not None
    assert active.id == row.id


async def test_get_active_treats_expired_session_as_ended():
    start_time = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    session = _FakeSession()
    svc = _service(session, now=start_time)
    admin = _user("superadmin")
    row = await svc.start(admin, customer_id=uuid4())

    # 61 minutes later — expired.
    later = start_time + datetime.timedelta(minutes=61)
    svc_read = _service(session, now=later)
    active = await svc_read.get_active(admin.id)

    assert active is None
    # Expired session is marked ended/inactive so it no longer lingers.
    assert row.active is False
    assert row.ended_at == later


async def test_get_active_returns_none_when_no_session():
    session = _FakeSession()
    svc = _service(session)
    assert await svc.get_active(uuid4()) is None


# ===========================================================================
# build_indicator — shape (Req 12.3)
# ===========================================================================


def test_build_indicator_for_customer():
    svc = ImpersonationService(_FakeSession())
    customer = uuid4()
    started = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    row = ImpersonationSession(
        impersonator_user_id=uuid4(),
        impersonated_customer_id=customer,
        active=True,
        started_at=started,
    )

    indicator = svc.build_indicator(row)

    assert indicator == {
        "impersonating": True,
        "impersonated_type": "customer",
        "impersonated_id": str(customer),
        "started_at": started.isoformat(),
    }


def test_build_indicator_for_agency():
    svc = ImpersonationService(_FakeSession())
    agency = uuid4()
    started = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    row = ImpersonationSession(
        impersonator_user_id=uuid4(),
        impersonated_agency_id=agency,
        active=True,
        started_at=started,
    )

    indicator = svc.build_indicator(row)

    assert indicator["impersonating"] is True
    assert indicator["impersonated_type"] == "agency"
    assert indicator["impersonated_id"] == str(agency)
    assert indicator["started_at"] == started.isoformat()


# ===========================================================================
# No re-auth / no IP or device restriction on start/end (Req 11.8)
# ===========================================================================
#
# Req 11.8: "THE Impersonation_Service SHALL start and end an
# Impersonation_Session without requiring re-authentication and without
# imposing IP address or device restrictions."
#
# We assert 11.8 at the API-shape level (neither start nor end accepts any
# credential/password/token/IP/device/user-agent parameter — so there is no
# surface through which such a gate could be imposed) and behaviourally (a
# start immediately followed by an end succeeds in one flow with only the
# impersonator identity + target, and no intervening authentication call).

import inspect

# Parameter names that would indicate a re-authentication step or an IP/device
# restriction being threaded into the lifecycle methods.
_REAUTH_PARAM_TOKENS = (
    "password",
    "credential",
    "token",
    "otp",
    "mfa",
    "reauth",
    "re_auth",
    "authenticate",
    "verify",
)
_IP_DEVICE_PARAM_TOKENS = (
    "ip",
    "ip_address",
    "device",
    "device_id",
    "user_agent",
    "useragent",
    "fingerprint",
    "client_ip",
    "remote_addr",
)


def _param_names(func) -> list[str]:  # noqa: ANN001
    return [
        name
        for name in inspect.signature(func).parameters
        if name not in ("self",)
    ]


def test_start_signature_has_no_reauth_or_ip_device_params():
    """Req 11.8 — ``start`` exposes no credential/IP/device parameter."""
    params = _param_names(ImpersonationService.start)

    # Only the impersonator identity and the target selectors are accepted.
    assert params == ["impersonator", "agency_id", "customer_id"]

    forbidden = _REAUTH_PARAM_TOKENS + _IP_DEVICE_PARAM_TOKENS
    for name in params:
        lowered = name.lower()
        assert not any(token in lowered for token in forbidden), (
            f"start() parameter {name!r} suggests a re-auth or IP/device gate, "
            "violating Requirement 11.8"
        )


def test_end_signature_has_no_reauth_or_ip_device_params():
    """Req 11.8 — ``end`` exposes no credential/IP/device parameter."""
    params = _param_names(ImpersonationService.end)

    # End takes only the session id — no credential, IP, or device context.
    assert params == ["session_id"]

    forbidden = _REAUTH_PARAM_TOKENS + _IP_DEVICE_PARAM_TOKENS
    for name in params:
        lowered = name.lower()
        assert not any(token in lowered for token in forbidden), (
            f"end() parameter {name!r} suggests a re-auth or IP/device gate, "
            "violating Requirement 11.8"
        )


async def test_start_then_end_succeeds_without_reauth_or_ip_device_context():
    """Req 11.8 — a start immediately followed by an end works in one flow.

    Only the impersonator identity + target are supplied to ``start`` and only
    the session id to ``end`` — there is no intervening authentication call and
    no IP/device context is threaded through. The flow completing proves the
    lifecycle imposes no re-auth or IP/device gate.
    """
    session = _FakeSession()
    svc = _service(session)
    admin = _user("superadmin")
    customer = uuid4()

    # Start with only impersonator + target (no credential / IP / device).
    started = await svc.start(admin, customer_id=customer)
    assert started.active is True

    # End immediately with only the session id — no re-authentication between.
    await svc.end(started.id)

    assert started.active is False
    assert started.ended_at is not None

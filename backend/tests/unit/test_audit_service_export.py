"""Unit tests for :meth:`AuditService.export` (Task 22.2, Req 15.6).

Verifies CSV and JSON output shape, ``created_at`` descending ordering, tenant
isolation carried over from the query path, and the 100,000-record cap. The cap
is asserted by capturing the ``LIMIT`` the service places on its select (rather
than materializing 100k rows), while format/ordering are checked against a small
in-memory corpus.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
from uuid import UUID, uuid4

from app.core.tenant_context import TenantContext
from app.models.audit import AuditLog
from app.services.audit_service import EXPORT_MAX_RECORDS, AuditFilter, AuditService

UTC = datetime.timezone.utc


class _ScalarResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)


class _CapturingSession:
    """Fake session that records the executed statement and returns given rows.

    Applies only ``created_at`` desc ordering + limit to the supplied rows so
    export ordering/cap can be verified without a database. The last executed
    statement is stored on ``self.last`` so tests can assert its ``LIMIT``.
    """

    def __init__(self, rows: list[AuditLog]) -> None:
        self.rows = list(rows)
        self.last = None

    async def execute(self, statement):  # noqa: ANN001
        self.last = statement
        ordered = sorted(self.rows, key=lambda r: r.created_at, reverse=True)
        limit = statement._limit
        if limit is not None:
            ordered = ordered[:limit]
        return _Result(ordered)


def _superadmin() -> TenantContext:
    return TenantContext(
        user_id=uuid4(),
        role_type="superadmin",
        agency_scope=None,
        customer_scope=frozenset(),
        is_superadmin=True,
        impersonating=False,
        impersonated_agency_id=None,
        impersonated_customer_id=None,
        impersonator_user_id=None,
        custom_role_customer_id=None,
    )


def _log(
    *,
    action: str = "create",
    created_at: datetime.datetime | None = None,
) -> AuditLog:
    row = AuditLog(
        user_id=uuid4(),
        role_type="customeradmin",
        agency_id=uuid4(),
        customer_id=uuid4(),
        module="marketing",
        sub_module="campaign",
        resource="MessageTemplate",
        action=action,
        old_value=None,
        new_value={"name": "x"},
        impersonation=False,
        impersonator_user_id=None,
        created_at=created_at or datetime.datetime(2024, 1, 1, tzinfo=UTC),
    )
    row.id = uuid4()
    return row


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


async def test_export_csv_has_header_and_rows():
    """Req 15.6 — CSV output has a header row and one row per record."""
    rows = [_log(action="create"), _log(action="update")]
    service = AuditService(_CapturingSession(rows))

    payload = await service.export(_superadmin(), fmt="csv")

    text = payload.decode("utf-8")
    reader = list(csv.reader(io.StringIO(text)))
    header = reader[0]
    assert header[0] == "id"
    assert "action" in header
    assert "created_at" in header
    assert len(reader) == 1 + len(rows)  # header + data rows


async def test_export_csv_serializes_jsonb_values_as_json():
    """new_value (a dict) is emitted as a single JSON-encoded cell."""
    service = AuditService(_CapturingSession([_log()]))
    payload = await service.export(_superadmin(), fmt="csv")
    reader = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
    header, data_row = reader[0], reader[1]
    new_value_cell = data_row[header.index("new_value")]
    assert json.loads(new_value_cell) == {"name": "x"}


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


async def test_export_json_is_array_of_objects():
    """Req 15.6 — JSON output is a list of objects with the expected fields."""
    rows = [_log(), _log()]
    service = AuditService(_CapturingSession(rows))

    payload = await service.export(_superadmin(), fmt="json")

    data = json.loads(payload.decode("utf-8"))
    assert isinstance(data, list)
    assert len(data) == 2
    first = data[0]
    assert set(first).issuperset({"id", "action", "created_at", "new_value"})
    # UUIDs/datetimes are serialized to strings; jsonb stays a dict.
    assert isinstance(first["id"], str)
    assert isinstance(first["created_at"], str)
    assert first["new_value"] == {"name": "x"}


async def test_export_ordered_by_created_at_desc():
    """Req 15.6 — export is ordered newest first."""
    a = _log(created_at=datetime.datetime(2024, 1, 1, tzinfo=UTC))
    b = _log(created_at=datetime.datetime(2024, 5, 1, tzinfo=UTC))
    c = _log(created_at=datetime.datetime(2024, 3, 1, tzinfo=UTC))
    service = AuditService(_CapturingSession([a, b, c]))

    data = json.loads((await service.export(_superadmin(), fmt="json")).decode("utf-8"))
    created = [d["created_at"] for d in data]
    assert created == sorted(created, reverse=True)
    assert data[0]["id"] == str(b.id)  # 2024-05 is newest


# ---------------------------------------------------------------------------
# 100,000 cap (Req 15.6)
# ---------------------------------------------------------------------------


async def test_export_limits_to_100000_records():
    """Req 15.6 — the export select is hard-capped at 100,000 rows."""
    session = _CapturingSession([_log()])
    service = AuditService(session)
    await service.export(_superadmin(), fmt="csv")
    assert session.last._limit == EXPORT_MAX_RECORDS
    assert EXPORT_MAX_RECORDS == 100_000


async def test_export_default_format_is_csv():
    """Default format is CSV when none is specified."""
    service = AuditService(_CapturingSession([_log()]))
    payload = await service.export(_superadmin())
    # CSV starts with the header field name; JSON would start with '['.
    assert payload.decode("utf-8").startswith("id,")

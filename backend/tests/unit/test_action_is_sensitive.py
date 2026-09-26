"""Unit tests for Action.is_sensitive default and persistence (Task 18.3).

Verify the ORM schema definition for the ``actions.is_sensitive`` flag matches
the design "Table Details → actions" at the metadata level (no live DB):
the column is Boolean, NOT NULL, defaults to false both Python-side
(``default=False``) and at the DB level (``server_default="false"``), and an
explicitly set ``True`` is reflected on the instance attribute (Req 13.1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.models import Action


def _cols(table):
    return {c.name: c for c in table.columns}


def test_actions_table_registered_on_metadata():
    assert "actions" in Base.metadata.tables


def test_is_sensitive_column_type_and_nullability():
    cols = _cols(Action.__table__)
    assert "is_sensitive" in cols
    col = cols["is_sensitive"]
    # Boolean type, NOT NULL (Req 13.1).
    assert isinstance(col.type, Boolean)
    assert not col.nullable


def test_is_sensitive_defaults_to_false():
    col = _cols(Action.__table__)["is_sensitive"]
    # DB-side server default corresponds to false.
    assert col.server_default is not None
    assert col.server_default.arg == "false"
    # Python/ORM-side default is False (a scalar column default).
    assert col.default is not None
    assert col.default.arg is False


def test_action_instance_defaults_to_false_without_explicit_value():
    # Constructing without is_sensitive: the ORM column default (False) is
    # applied at flush/insert time. The column-level default is asserted above;
    # here we confirm no explicit truthy value leaks in on construction.
    action = Action(
        resource_id=uuid.uuid4(),
        name="read",
        action_key="m.s.r.read",
    )
    # Before flush the attribute is unset/None (default applied at insert),
    # and it is certainly not True.
    assert action.is_sensitive in (None, False)


def test_action_instance_persists_explicit_true():
    action = Action(
        resource_id=uuid.uuid4(),
        name="delete",
        action_key="m.s.r.delete",
        is_sensitive=True,
    )
    assert action.is_sensitive is True

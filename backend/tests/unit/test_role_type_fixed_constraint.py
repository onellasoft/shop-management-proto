"""Unit tests for the fixed ``role_type`` constraint (Task 2.2).

Requirement 4.1: the API backend SHALL support exactly three Role_Type
values (superadmin, agencyadmin, customeradmin) and SHALL NOT permit any
additional Role_Type value to be created, renamed, or deleted.

Role_Type is modelled as a *hardcoded enumeration* backed by the
``ck_users_role_type`` CHECK constraint on the ``users`` table — it is not a
data-driven lookup table. These tests assert the enumeration is exactly the
three fixed values and that the fixed set is immutable at the model level:
there is no persistence surface through which a role_type row could be
created, renamed, or deleted, and any value outside the fixed set is rejected
by the CHECK constraint.
"""

from __future__ import annotations

import re

import pytest

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.models.user import ROLE_TYPES, User

FIXED_ROLE_TYPES = ("superadmin", "agencyadmin", "customeradmin")


def _role_type_check():
    return next(
        c
        for c in User.__table__.constraints
        if getattr(c, "name", None) == "ck_users_role_type"
    )


def _allowed_literals():
    """The set of quoted values the CHECK constraint admits."""
    return set(re.findall(r"'([^']+)'", str(_role_type_check().sqltext)))


def test_exactly_three_fixed_role_type_values():
    # Exactly three, in the canonical order, no more and no fewer.
    assert ROLE_TYPES == FIXED_ROLE_TYPES
    assert len(ROLE_TYPES) == 3
    assert len(set(ROLE_TYPES)) == 3  # no duplicates


def test_check_constraint_enumerates_exactly_the_three_values():
    # The admitted set is exactly the three fixed values — no more, no fewer,
    # so the enumeration is closed (no other quoted literal appears).
    assert _allowed_literals() == set(FIXED_ROLE_TYPES)


def test_role_type_is_not_a_data_driven_table():
    # A fixed enumeration must not be backed by a create/rename/delete-able
    # lookup table. Assert no such table exists in the mapped metadata.
    table_names = set(Base.metadata.tables.keys())
    for forbidden in ("role_types", "role_type", "roletypes"):
        assert forbidden not in table_names


def test_creating_a_new_role_type_value_is_rejected():
    # A brand-new role_type value has no home: it is not in the fixed set and
    # is not admitted by the CHECK constraint enumeration.
    new_value = "regionadmin"
    assert new_value not in ROLE_TYPES
    assert new_value not in _allowed_literals()


def test_renaming_a_role_type_value_is_rejected():
    # "Renaming" an existing role_type would change one of the three literals.
    # Assert the canonical names are exactly the admitted set and that renamed
    # variants (rename targets) are not admitted.
    allowed = _allowed_literals()
    assert allowed == set(FIXED_ROLE_TYPES)
    for renamed in ("super_admin", "agency_admin", "customer_admin", "admin"):
        assert renamed not in allowed


def test_deleting_a_role_type_value_is_rejected():
    # Deletion would shrink the enumeration below three; assert all three
    # remain admitted and the tuple length is fixed at three.
    assert _allowed_literals() == set(FIXED_ROLE_TYPES)
    assert len(ROLE_TYPES) == 3


@pytest.mark.parametrize("bad_value", ["", "SUPERADMIN", "agency", "root", "owner"])
def test_values_outside_the_fixed_set_are_not_permitted(bad_value):
    assert bad_value not in ROLE_TYPES
    assert bad_value not in _allowed_literals()

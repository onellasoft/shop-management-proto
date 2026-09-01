"""Unit tests for the global action set and action-creation rejection (Task 8.4).

Requirement 5.2: THE API_Backend SHALL define the set of Actions globally and
SHALL include the four standard Actions create, read, update, and delete in
addition to any custom Actions.

Requirement 5.4: IF a request attempts to create a new Action, THEN THE
Authorization_Service SHALL reject the request, return an authorization error
indicating that Actions are predefined globally and cannot be created
(``action_not_creatable``), and leave the global set of Actions unchanged.

Actions are seeded globally from ``app.core.permission_seed`` (the four
standard actions applied to every resource); there is no create-action service
method or API surface. These tests therefore assert:

1. The four standard actions ``create`` / ``read`` / ``update`` / ``delete``
   are part of the global action set — both as the declared ``STANDARD_ACTIONS``
   tuple and as the action names materialized by ``iter_action_keys()``.
2. Attempting to create a new Action is rejected via ``ActionNotCreatableError``
   carrying the ``action_not_creatable`` code, and no create-action surface
   exists in the Authorization_Service.
"""

from __future__ import annotations

import pytest

from app.core.errors import ActionNotCreatableError, ErrorCode
from app.core.permission_seed import STANDARD_ACTIONS, iter_action_keys

STANDARD = ("create", "read", "update", "delete")


# ---------------------------------------------------------------------------
# Requirement 5.2 — the four standard actions are part of the global action set
# ---------------------------------------------------------------------------


def test_standard_actions_are_exactly_the_four_crud_actions():
    # The declared global standard action set is exactly create/read/update/delete.
    assert STANDARD_ACTIONS == STANDARD
    assert set(STANDARD_ACTIONS) == {"create", "read", "update", "delete"}


@pytest.mark.parametrize("action", STANDARD)
def test_each_standard_action_is_declared_globally(action):
    assert action in STANDARD_ACTIONS


def test_standard_actions_present_in_iter_action_keys():
    # Every action name materialized from the permission graph is one of the
    # four global standard actions, and all four appear at least once.
    materialized = {row[3] for row in iter_action_keys()}  # action_name column
    assert materialized == set(STANDARD_ACTIONS)
    for action in STANDARD_ACTIONS:
        assert action in materialized


def test_every_resource_gets_the_four_standard_actions():
    # For each (module, submodule, resource), the four standard actions are all
    # present in the flattened global action set.
    rows = iter_action_keys()
    by_resource: dict[tuple[str, str, str], set[str]] = {}
    for module, submodule, resource, action, _key, _sensitive in rows:
        by_resource.setdefault((module, submodule, resource), set()).add(action)

    assert by_resource, "expected at least one resource in the permission graph"
    for resource_key, actions in by_resource.items():
        assert actions == set(STANDARD_ACTIONS), (
            f"resource {resource_key} is missing standard actions: "
            f"{set(STANDARD_ACTIONS) - actions}"
        )


def test_action_keys_end_with_a_standard_action():
    # The denormalized action_key is module.submodule.resource.action; its final
    # segment must be one of the four global standard actions.
    for _m, _s, _r, action, action_key, _sensitive in iter_action_keys():
        assert action_key.endswith(f".{action}")
        assert action_key.rsplit(".", 1)[-1] in STANDARD_ACTIONS


# ---------------------------------------------------------------------------
# Requirement 5.4 — creating a new Action is rejected with action_not_creatable
# ---------------------------------------------------------------------------


def test_action_not_creatable_error_carries_the_expected_code():
    err = ActionNotCreatableError()
    assert err.code is ErrorCode.ACTION_NOT_CREATABLE
    assert err.code.value == "action_not_creatable"


def test_action_not_creatable_error_serializes_to_standard_envelope():
    err = ActionNotCreatableError()
    body = err.to_dict()
    assert body["error"]["code"] == "action_not_creatable"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert body["error"]["details"] == {}


def test_action_not_creatable_error_is_forbidden():
    # Attempting to create a globally-defined action is an authorization error.
    assert ActionNotCreatableError().http_status == 403


def test_action_not_creatable_error_is_raisable():
    with pytest.raises(ActionNotCreatableError) as excinfo:
        raise ActionNotCreatableError()
    assert excinfo.value.code.value == "action_not_creatable"


def test_no_create_action_service_surface_exists():
    # Actions are defined globally in permission_seed — there is deliberately no
    # runtime create-action method. Assert the Authorization_Service exposes no
    # such surface (if the service module exists yet).
    try:
        import app.services.authorization_service as authz
    except ImportError:
        pytest.skip("Authorization_Service not implemented yet")
        return

    forbidden_names = ("create_action", "add_action", "new_action")
    for name in forbidden_names:
        assert not hasattr(authz, name), (
            f"unexpected create-action surface: {name}"
        )
        for cls_name in dir(authz):
            obj = getattr(authz, cls_name)
            if isinstance(obj, type):
                assert not hasattr(obj, name), (
                    f"unexpected create-action method {cls_name}.{name}"
                )

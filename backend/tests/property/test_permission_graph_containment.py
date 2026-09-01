"""Property-based test for permission graph containment integrity.

# Feature: onella-backend, Property 11: Permission graph containment integrity

**Validates: Requirements 5.1**

Requirement 5.1 states that the API_Backend organizes functionality so that
each Module contains one or more SubModules, each SubModule belongs to exactly
one Module, each SubModule contains one or more Resources, each Resource
belongs to exactly one SubModule, each Resource has one or more associated
Actions, and each Action is associated with exactly one Resource.

Property 11 (design): *For any* generated permission graph, every SubModule
belongs to exactly one Module, every Resource belongs to exactly one SubModule,
and every Action is associated with exactly one Resource.

The canonical permission graph is defined in ``app.core.permission_seed`` and
flattened by :func:`iter_action_keys`. This test samples over the generated
action tuples (via ``st.sampled_from``) and asserts, for each sampled entry:

* the ``action_key`` decomposes exactly as ``module.submodule.resource.action``;
* each parent level exists in the graph and *contains* its child; and
* containment is single-parent — each submodule key maps to exactly one module,
  each ``(module, submodule)`` resource key maps to exactly one submodule, and
  each full ``action_key`` maps to exactly one resource — i.e. no child is
  reachable under two different parents anywhere in the graph.
"""

from __future__ import annotations

from collections import defaultdict

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.permission_seed import (
    PERMISSION_GRAPH,
    STANDARD_ACTIONS,
    iter_action_keys,
)

# ---------------------------------------------------------------------------
# Precompute the containment maps ONCE from the graph. These encode the
# "belongs to exactly one parent" invariant: if any child appeared under two
# parents, the corresponding set below would have more than one element.
# ---------------------------------------------------------------------------

# submodule key -> set of module keys that contain it
_submodule_to_modules: dict[str, set[str]] = defaultdict(set)
# (module, submodule, resource) -> set of (module, submodule) parents
_resource_to_submodules: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(
    set
)
# action_key -> set of (module, submodule, resource) parents
_action_to_resources: dict[str, set[tuple[str, str, str]]] = defaultdict(set)

# Existence sets for quick "parent exists / contains child" checks.
_modules: set[str] = set()
_module_submodules: set[tuple[str, str]] = set()
_submodule_resources: set[tuple[str, str, str]] = set()

for _module in PERMISSION_GRAPH:
    _modules.add(_module["key"])
    for _submodule in _module["submodules"]:
        _submodule_to_modules[_submodule["key"]].add(_module["key"])
        _module_submodules.add((_module["key"], _submodule["key"]))
        for _resource in _submodule["resources"]:
            _resource_to_submodules[
                (_module["key"], _submodule["key"], _resource["key"])
            ].add((_module["key"], _submodule["key"]))
            _submodule_resources.add(
                (_module["key"], _submodule["key"], _resource["key"])
            )

for _row in iter_action_keys():
    _m, _s, _r, _a, _key, _sensitive = _row
    _action_to_resources[_key].add((_m, _s, _r))


# The strategy samples over the generated graph entries (Req 5.1 / Property 11).
_action_rows = st.sampled_from(iter_action_keys())


@settings(max_examples=100, deadline=None)
@given(row=_action_rows)
def test_permission_graph_containment_integrity(
    row: tuple[str, str, str, str, str, bool],
) -> None:
    """Every action tuple satisfies four-level containment integrity (Req 5.1)."""
    module_key, submodule_key, resource_key, action_name, action_key, _sensitive = row

    # 1. The action_key decomposes exactly as module.submodule.resource.action.
    assert action_key == f"{module_key}.{submodule_key}.{resource_key}.{action_name}"
    assert action_key.split(".") == [
        module_key,
        submodule_key,
        resource_key,
        action_name,
    ]

    # 2. Each parent level exists and contains its child.
    assert module_key in _modules
    assert (module_key, submodule_key) in _module_submodules
    assert (module_key, submodule_key, resource_key) in _submodule_resources
    assert action_name in STANDARD_ACTIONS

    # 3. Single-parent containment: each child belongs to exactly one parent.
    # Each SubModule belongs to exactly one Module.
    assert _submodule_to_modules[submodule_key] == {module_key}
    # Each Resource belongs to exactly one SubModule.
    assert _resource_to_submodules[(module_key, submodule_key, resource_key)] == {
        (module_key, submodule_key)
    }
    # Each Action (by its full key) is associated with exactly one Resource.
    assert _action_to_resources[action_key] == {
        (module_key, submodule_key, resource_key)
    }

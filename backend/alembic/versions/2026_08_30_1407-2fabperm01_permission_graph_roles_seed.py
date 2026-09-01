"""permission graph roles seed

Revision ID: 2fabperm01
Revises: fc94b119d8b4
Create Date: 2026-08-30 14:07:33.472819+00:00

Creates the permission/role graph tables and seeds them (task 8.3):

Tables (design "Table Details"):
* ``modules``          — top level of the four-level permission graph (Req 5.1)
* ``submodules``       — belongs to one module (Req 5.1)
* ``resources``        — belongs to one submodule (Req 5.1)
* ``actions``          — leaf; create/read/update/delete + is_sensitive (Req 5.2, 13.1)
                         with a denormalized indexed ``action_key``
* ``roles``            — three fixed system roles + customer-scoped custom roles (Req 4.1, 7.2)
* ``role_permissions`` — grants an Action to a Role (Req 5.3)
* ``user_roles``       — assigns a Role to a User (optionally per Customer)

Seed data (task 8.3), all sourced from ``app.core.permission_seed`` so the
migration and the runtime services share one canonical definition:
* The permission graph (modules/submodules/resources/actions) with the four
  standard actions per resource, ``is_sensitive`` set per resource override and
  defaulting false (Req 5.2, 13.1), and a denormalized ``action_key``.
* The three fixed roles ``superadmin`` / ``agencyadmin`` / ``customeradmin``
  with ``is_custom=false`` and ``role_type`` set (Req 4.1).

Default custom roles (Req 7.1) — ``finance_manager`` / ``staff`` /
``inventory_manager`` — are NOT seeded as rows here. The ``roles`` table
requires a non-null ``customer_id`` for any custom role
(``ck_roles_custom_requires_customer_and_name``), because a Custom_Role is
scoped to a single Customer (Req 7.2). They are therefore provided as reusable
TEMPLATES in ``app.core.permission_seed.DEFAULT_CUSTOM_ROLE_TEMPLATES`` and
instantiated into concrete per-Customer roles by the Authorization_Service at
Customer onboarding (task 11). See that module's docstring for the rationale.

This migration is deterministic: all UUIDs are generated at upgrade time and
bulk-inserted, so ``alembic upgrade --sql`` (offline) produces the full INSERT
set without a live database.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.permission_seed import (
    FIXED_ROLE_TYPES,
    PERMISSION_GRAPH,
    STANDARD_ACTIONS,
    iter_action_keys,
)


# revision identifiers, used by Alembic.
revision: str = '2fabperm01'
down_revision: str | None = 'fc94b119d8b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_tables() -> None:
    # --- modules ------------------------------------------------------------
    op.create_table(
        "modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modules")),
        sa.UniqueConstraint("key", name="ux_modules_key"),
    )

    # --- submodules ---------------------------------------------------------
    op.create_table(
        "submodules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["modules.id"],
            name=op.f("fk_submodules_module_id_modules"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submodules")),
        sa.UniqueConstraint("module_id", "key", name="ux_submodules_module_key"),
    )
    op.create_index("ix_submodules_module_id", "submodules", ["module_id"])

    # --- resources ----------------------------------------------------------
    op.create_table(
        "resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submodule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(
            ["submodule_id"],
            ["submodules.id"],
            name=op.f("fk_resources_submodule_id_submodules"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resources")),
        sa.UniqueConstraint(
            "submodule_id", "key", name="ux_resources_submodule_key"
        ),
    )
    op.create_index("ix_resources_submodule_id", "resources", ["submodule_id"])

    # --- actions ------------------------------------------------------------
    op.create_table(
        "actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "is_sensitive",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("action_key", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name=op.f("fk_actions_resource_id_resources"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actions")),
        sa.UniqueConstraint("resource_id", "name", name="ux_actions_resource_name"),
    )
    op.create_index("ix_actions_action_key", "actions", ["action_key"])

    # --- roles --------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_type", sa.String(length=20), nullable=True),
        sa.Column(
            "is_custom",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "(is_custom = false) OR "
            "(customer_id IS NOT NULL AND name IS NOT NULL "
            "AND char_length(name) BETWEEN 1 AND 100)",
            name="ck_roles_custom_requires_customer_and_name",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_roles_customer_id_customers"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("customer_id", "name", name="ux_roles_customer_name"),
    )
    op.create_index("ix_roles_customer_id", "roles", ["customer_id"])

    # --- role_permissions ---------------------------------------------------
    op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["actions.id"],
            name=op.f("fk_role_permissions_action_id_actions"),
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_permissions")),
        sa.UniqueConstraint(
            "role_id", "action_id", name="ux_role_permissions_role_action"
        ),
    )
    op.create_index(
        "ix_role_permissions_role_id", "role_permissions", ["role_id"]
    )
    op.create_index(
        "ix_role_permissions_action_id", "role_permissions", ["action_id"]
    )

    # --- user_roles ---------------------------------------------------------
    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_user_roles_customer_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_user_roles_role_id_roles"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_roles_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_roles")),
        sa.UniqueConstraint(
            "user_id",
            "role_id",
            "customer_id",
            name="ux_user_roles_user_role_customer",
        ),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])


def _seed_permission_graph() -> None:
    """Seed modules/submodules/resources/actions and the three fixed roles.

    All identifiers are minted here so the INSERTs are fully deterministic and
    render under ``alembic upgrade --sql`` (offline) without a database.
    """
    # Lightweight table handles for bulk_insert.
    modules_t = sa.table(
        "modules",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.String),
        sa.column("name", sa.String),
    )
    submodules_t = sa.table(
        "submodules",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("module_id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.String),
        sa.column("name", sa.String),
    )
    resources_t = sa.table(
        "resources",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("submodule_id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.String),
        sa.column("name", sa.String),
    )
    actions_t = sa.table(
        "actions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("is_sensitive", sa.Boolean),
        sa.column("action_key", sa.String),
    )
    roles_t = sa.table(
        "roles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("role_type", sa.String),
        sa.column("is_custom", sa.Boolean),
        sa.column("customer_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
    )

    module_rows: list[dict] = []
    submodule_rows: list[dict] = []
    resource_rows: list[dict] = []
    action_rows: list[dict] = []

    # Map (module_key), (module_key, sub_key), (module_key, sub_key, res_key)
    # to the minted UUIDs so children can reference their parents.
    resource_ids: dict[tuple[str, str, str], uuid.UUID] = {}

    for module in PERMISSION_GRAPH:
        module_id = uuid.uuid4()
        module_rows.append(
            {"id": module_id, "key": module["key"], "name": module["name"]}
        )
        for submodule in module["submodules"]:
            submodule_id = uuid.uuid4()
            submodule_rows.append(
                {
                    "id": submodule_id,
                    "module_id": module_id,
                    "key": submodule["key"],
                    "name": submodule["name"],
                }
            )
            for resource in submodule["resources"]:
                resource_id = uuid.uuid4()
                resource_rows.append(
                    {
                        "id": resource_id,
                        "submodule_id": submodule_id,
                        "key": resource["key"],
                        "name": resource["name"],
                    }
                )
                resource_ids[
                    (module["key"], submodule["key"], resource["key"])
                ] = resource_id

    # Actions: one row per (resource, standard action), with denormalized
    # action_key and per-resource sensitivity override (default false).
    for (
        module_key,
        submodule_key,
        resource_key,
        action_name,
        action_key,
        is_sensitive,
    ) in iter_action_keys():
        action_rows.append(
            {
                "id": uuid.uuid4(),
                "resource_id": resource_ids[
                    (module_key, submodule_key, resource_key)
                ],
                "name": action_name,
                "is_sensitive": is_sensitive,
                "action_key": action_key,
            }
        )

    op.bulk_insert(modules_t, module_rows)
    op.bulk_insert(submodules_t, submodule_rows)
    op.bulk_insert(resources_t, resource_rows)
    op.bulk_insert(actions_t, action_rows)

    # --- three fixed system roles (Req 4.1) ---------------------------------
    # is_custom=false, role_type set, no customer_id/name.
    op.bulk_insert(
        roles_t,
        [
            {
                "id": uuid.uuid4(),
                "role_type": role_type,
                "is_custom": False,
                "customer_id": None,
                "name": None,
            }
            for role_type in FIXED_ROLE_TYPES
        ],
    )
    # NOTE: default custom roles (finance_manager/staff/inventory_manager,
    # Req 7.1) are provided as templates in app.core.permission_seed and
    # instantiated per-Customer by the Authorization_Service (task 11); they are
    # intentionally NOT seeded here because the schema requires a customer_id
    # for any custom role.


def upgrade() -> None:
    _create_tables()
    _seed_permission_graph()


def downgrade() -> None:
    # Drop in reverse dependency order. Rows are removed implicitly with their
    # tables, so the seed data needs no explicit DELETE.
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")

    op.drop_index(
        "ix_role_permissions_action_id", table_name="role_permissions"
    )
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")

    op.drop_index("ix_roles_customer_id", table_name="roles")
    op.drop_table("roles")

    op.drop_index("ix_actions_action_key", table_name="actions")
    op.drop_table("actions")

    op.drop_index("ix_resources_submodule_id", table_name="resources")
    op.drop_table("resources")

    op.drop_index("ix_submodules_module_id", table_name="submodules")
    op.drop_table("submodules")

    op.drop_table("modules")

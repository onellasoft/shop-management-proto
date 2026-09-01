"""Canonical seed data for the permission graph and default roles.

This module is the single source of truth for:

* The **permission graph** — the Module → SubModule → Resource → Action tree
  seeded into ``modules`` / ``submodules`` / ``resources`` / ``actions`` by the
  ``2fab_permission_graph`` Alembic migration (Req 5.1, 5.2, 13.1).
* The four **standard actions** (``create`` / ``read`` / ``update`` / ``delete``)
  applied to every resource (Req 5.2).
* The three **fixed system roles** (Req 4.1).
* The **default custom-role templates** ``finance_manager`` / ``staff`` /
  ``inventory_manager`` (Req 7.1).

Design note — default custom roles are TEMPLATES, not global rows
-----------------------------------------------------------------
The ``roles`` table enforces (design "Table Details → roles",
``ck_roles_custom_requires_customer_and_name``) that a custom role
(``is_custom=true``) MUST carry a non-null ``customer_id`` and a name of length
1–100, because "A Custom_Role is a named collection of Action permissions
defined within the scope of a single Customer" (requirements glossary, Req 7.2).

Therefore the three default custom roles cannot be seeded as customer-less rows
in ``roles`` without violating the schema. Instead they are defined here as
reusable **templates**: each names a set of ``action_key`` values. When a
Customer is onboarded (or on demand), the Authorization_Service instantiates
these templates as concrete, customer-scoped ``roles`` rows plus their
``role_permissions`` grants (task 11 — ``create_custom_role`` /
``clone_custom_role``). This satisfies Req 7.1 ("provide default Custom_Roles
including finance_manager, staff, and inventory_manager") while honoring the
per-Customer scoping constraint.

Keeping the definitions here (rather than inline in the migration) lets both the
migration and the runtime services share exactly one definition, so the seeded
graph and the templates never drift apart.
"""

from __future__ import annotations

from typing import Final, TypedDict

# ---------------------------------------------------------------------------
# Standard actions (Req 5.2)
# ---------------------------------------------------------------------------
# Every Resource gets these four standard Actions. ``is_sensitive`` defaults to
# false (Req 13.1); a per-(resource, action) override is applied where a
# standard action is inherently sensitive (see SENSITIVE_ACTION_KEYS below).
STANDARD_ACTIONS: Final[tuple[str, ...]] = ("create", "read", "update", "delete")


# ---------------------------------------------------------------------------
# Fixed system roles (Req 4.1)
# ---------------------------------------------------------------------------
# The three role_type values. Seeded with is_custom=false and role_type set.
FIXED_ROLE_TYPES: Final[tuple[str, ...]] = (
    "superadmin",
    "agencyadmin",
    "customeradmin",
)


class ResourceDef(TypedDict):
    key: str
    name: str
    # action_keys that are sensitive for THIS resource (Req 13.1). The action
    # itself defaults to non-sensitive; only these overrides set is_sensitive.
    sensitive_actions: tuple[str, ...]


class SubModuleDef(TypedDict):
    key: str
    name: str
    resources: tuple[ResourceDef, ...]


class ModuleDef(TypedDict):
    key: str
    name: str
    submodules: tuple[SubModuleDef, ...]


def _resource(
    key: str, name: str, sensitive_actions: tuple[str, ...] = ()
) -> ResourceDef:
    return {"key": key, "name": name, "sensitive_actions": sensitive_actions}


# ---------------------------------------------------------------------------
# Permission graph (Req 5.1, 5.2, 13.1)
# ---------------------------------------------------------------------------
# Modules mirror the requirements glossary examples: Billing, Inventory
# Management, Logistics, Marketing, Promotion. Each Module → SubModule →
# Resource carries the four standard Actions. A handful of destructive/financial
# actions are flagged sensitive so they are blocked during impersonation
# (Req 13.x); everything else is non-sensitive by default (Req 13.1).
PERMISSION_GRAPH: Final[tuple[ModuleDef, ...]] = (
    {
        "key": "billing",
        "name": "Billing",
        "submodules": (
            {
                "key": "invoices",
                "name": "Invoices",
                "resources": (
                    # Deleting an invoice is financially sensitive.
                    _resource("invoice", "Invoice", sensitive_actions=("delete",)),
                    _resource("invoice_line_item", "Invoice Line Item"),
                ),
            },
            {
                "key": "payments",
                "name": "Payments",
                "resources": (
                    # Creating/deleting payments moves money — sensitive.
                    _resource(
                        "payment",
                        "Payment",
                        sensitive_actions=("create", "delete"),
                    ),
                    _resource("refund", "Refund", sensitive_actions=("create",)),
                ),
            },
        ),
    },
    {
        "key": "inventory_management",
        "name": "Inventory Management",
        "submodules": (
            {
                "key": "catalog",
                "name": "Catalog",
                "resources": (
                    _resource("product", "Product"),
                    _resource("category", "Category"),
                ),
            },
            {
                "key": "stock",
                "name": "Stock",
                "resources": (
                    _resource("stock_item", "Stock Item"),
                    # Stock adjustments can hide shrinkage — sensitive.
                    _resource(
                        "stock_adjustment",
                        "Stock Adjustment",
                        sensitive_actions=("create", "delete"),
                    ),
                ),
            },
        ),
    },
    {
        "key": "logistics",
        "name": "Logistics",
        "submodules": (
            {
                "key": "shipments",
                "name": "Shipments",
                "resources": (
                    _resource("shipment", "Shipment"),
                    _resource("carrier", "Carrier"),
                ),
            },
            {
                "key": "warehouses",
                "name": "Warehouses",
                "resources": (
                    _resource("warehouse", "Warehouse"),
                ),
            },
        ),
    },
    {
        "key": "marketing",
        "name": "Marketing",
        "submodules": (
            {
                "key": "campaign",
                "name": "Campaign",
                "resources": (
                    # Sending a campaign (create) reaches customers — sensitive.
                    _resource(
                        "campaign",
                        "Campaign",
                        sensitive_actions=("create", "delete"),
                    ),
                    _resource("message_template", "Message Template"),
                ),
            },
            {
                "key": "contacts",
                "name": "Contacts",
                "resources": (
                    _resource("contact", "Contact"),
                    _resource("contact_group", "Contact Group"),
                ),
            },
        ),
    },
    {
        "key": "promotion",
        "name": "Promotion",
        "submodules": (
            {
                "key": "offers",
                "name": "Offers",
                "resources": (
                    _resource("offer", "Offer"),
                    _resource("coupon", "Coupon", sensitive_actions=("create",)),
                ),
            },
        ),
    },
)


def iter_action_keys() -> list[tuple[str, str, str, str, str, bool]]:
    """Flatten the permission graph into action tuples.

    Returns
    -------
    list of ``(module_key, submodule_key, resource_key, action_name,
    action_key, is_sensitive)`` where ``action_key`` is the denormalized
    ``module.submodule.resource.action`` string used for fast per-request
    lookup (design "actions" table).
    """
    rows: list[tuple[str, str, str, str, str, bool]] = []
    for module in PERMISSION_GRAPH:
        for submodule in module["submodules"]:
            for resource in submodule["resources"]:
                for action in STANDARD_ACTIONS:
                    action_key = (
                        f"{module['key']}.{submodule['key']}."
                        f"{resource['key']}.{action}"
                    )
                    is_sensitive = action in resource["sensitive_actions"]
                    rows.append(
                        (
                            module["key"],
                            submodule["key"],
                            resource["key"],
                            action,
                            action_key,
                            is_sensitive,
                        )
                    )
    return rows


# ---------------------------------------------------------------------------
# Default custom-role templates (Req 7.1)
# ---------------------------------------------------------------------------
# These are TEMPLATES (see module docstring). Each maps a role name to the set
# of action_keys it grants. The Authorization_Service instantiates a template
# into a concrete customer-scoped role + role_permissions when a Customer is
# onboarded (task 11). Action keys reference PERMISSION_GRAPH entries above.
DEFAULT_CUSTOM_ROLE_TEMPLATES: Final[dict[str, tuple[str, ...]]] = {
    "finance_manager": (
        "billing.invoices.invoice.create",
        "billing.invoices.invoice.read",
        "billing.invoices.invoice.update",
        "billing.invoices.invoice.delete",
        "billing.invoices.invoice_line_item.create",
        "billing.invoices.invoice_line_item.read",
        "billing.invoices.invoice_line_item.update",
        "billing.invoices.invoice_line_item.delete",
        "billing.payments.payment.create",
        "billing.payments.payment.read",
        "billing.payments.payment.update",
        "billing.payments.payment.delete",
        "billing.payments.refund.create",
        "billing.payments.refund.read",
    ),
    "staff": (
        # Read-mostly access across customer-facing modules.
        "marketing.campaign.campaign.read",
        "marketing.campaign.message_template.read",
        "marketing.contacts.contact.create",
        "marketing.contacts.contact.read",
        "marketing.contacts.contact.update",
        "marketing.contacts.contact_group.read",
        "promotion.offers.offer.read",
        "promotion.offers.coupon.read",
        "billing.invoices.invoice.read",
    ),
    "inventory_manager": (
        "inventory_management.catalog.product.create",
        "inventory_management.catalog.product.read",
        "inventory_management.catalog.product.update",
        "inventory_management.catalog.product.delete",
        "inventory_management.catalog.category.create",
        "inventory_management.catalog.category.read",
        "inventory_management.catalog.category.update",
        "inventory_management.catalog.category.delete",
        "inventory_management.stock.stock_item.create",
        "inventory_management.stock.stock_item.read",
        "inventory_management.stock.stock_item.update",
        "inventory_management.stock.stock_item.delete",
        "inventory_management.stock.stock_adjustment.create",
        "inventory_management.stock.stock_adjustment.read",
        "logistics.warehouses.warehouse.read",
    ),
}


__all__ = [
    "STANDARD_ACTIONS",
    "FIXED_ROLE_TYPES",
    "PERMISSION_GRAPH",
    "DEFAULT_CUSTOM_ROLE_TEMPLATES",
    "iter_action_keys",
]

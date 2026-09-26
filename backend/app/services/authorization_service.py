"""Authorization_Service — permission evaluation and (later) tenant scoping.

This module implements **per-request permission evaluation** (Task 9.1),
module-subscription gating (10.2), custom-role management (11.x), and
**tenant-context derivation** (Task 13.1). Later tasks layer the customer-list
Redis cache (15.x) and the ORM tenant filter (14.1) onto this same service.

Design reference: "Components and Interfaces → Authorization_Service"::

    async def has_permission(self, ctx: TenantContext, action_key: str) -> bool:
        \"\"\"Read the permission from the DB on THIS request and return whether
        the acting user holds it. Superadmin bypasses (Req 4.2). Fail-closed
        on any DB read error (Req 6.3).\"\"\"

Evaluation semantics
--------------------
* **Superadmin bypass** (Req 4.2): a superadmin has unrestricted access to
  every Action, so ``has_permission`` short-circuits to ``True`` without
  touching the database.
* **Per-request DB read** (Req 6.1, 6.4): for every other principal the grant
  is read from the database on the same request. Because nothing is cached,
  revoking a permission (deleting the ``role_permissions`` row) takes effect on
  the very next request that is enforced after the revocation is persisted.
* **Single-action granularity** (Req 5.3): the lookup keys off the target
  ``actions.action_key`` and asks only whether *some* role assigned to the user
  grants *that one* Action.
* **Custom-role scoping**: when the context is acting under a custom role
  (``custom_role_customer_id`` set), only role assignments scoped to that same
  customer are considered, so a grant in one customer cannot leak into another.
* **Fail-closed** (Req 6.3): any error while reading the grant from the
  database is treated as "no permission" and raised as
  :class:`NotAuthorizedError`; the caller must not execute the Action.

The join walked on each request is::

    user_roles → roles → role_permissions → actions

filtered by ``user_roles.user_id == ctx.user_id`` and
``actions.action_key == action_key``. Existence of any matching row means the
user holds the permission.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.customer_list_cache import (
    AgencyCustomerListCache,
    get_agency_customer_list_cache,
)
from app.core.errors import (
    ActionModuleUnsubscribedError,
    NotAuthorizedError,
    RoleNameConflictError,
    TenantContextMissingError,
    ValidationError,
)
from app.core.security import AccessTokenClaims
from app.core.tenant_context import TenantContext
from app.models.customer import Customer
from app.models.customer_user import CustomerUser
from app.models.permission import Action, Resource, SubModule
from app.models.role import Role, RolePermission, UserRole
from app.models.subscription import CustomerSubscription
from app.models.user import ROLE_TYPES

# Custom-role name length bounds (Req 7.2).
_ROLE_NAME_MIN_LEN = 1
_ROLE_NAME_MAX_LEN = 100


def _utcnow() -> datetime.datetime:
    """Return the current timezone-aware UTC time (default module clock)."""
    return datetime.datetime.now(datetime.timezone.utc)


class AuthorizationService:
    """Permission and (later) tenant-isolation enforcement (Req 6, 9).

    Instantiated per request with the active :class:`AsyncSession` so every
    permission check reads live database state (Req 6.1).
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        now: Callable[[], datetime.datetime] | None = None,
        customer_list_cache: AgencyCustomerListCache | None = None,
    ) -> None:
        self._session = session
        # Injectable clock for time-dependent checks (e.g. subscription
        # expiry). Defaults to real UTC time; tests supply a fake clock.
        self._now = now if now is not None else _utcnow
        # Agency accessible-customer-list cache (Req 10). Defaults to the shared
        # Redis-backed cache; tests inject an in-memory fake. Constructed lazily
        # only when first needed so services that never derive an agencyadmin
        # scope (e.g. permission-only checks) don't touch Redis.
        self._customer_list_cache = customer_list_cache

    async def has_permission(self, ctx: TenantContext, action_key: str) -> bool:
        """Return whether ``ctx`` holds a permission for ``action_key``.

        Reads the grant from the database on this request (Req 6.1). A
        superadmin bypasses the check entirely (Req 4.2). Any failure to read
        the permission is fail-closed: the request is denied with
        :class:`NotAuthorizedError` (Req 6.3).

        Parameters
        ----------
        ctx:
            The immutable per-request tenant context identifying the acting
            user and, where applicable, the custom-role customer scope.
        action_key:
            The denormalized ``module.submodule.resource.action`` key of the
            Action being attempted.

        Returns
        -------
        bool
            ``True`` when the user holds the permission, ``False`` otherwise.

        Raises
        ------
        NotAuthorizedError
            When the permission cannot be read from the database
            (fail-closed, Req 6.3).
        """
        # Req 4.2 — superadmin has no tenant boundary and holds every Action.
        if ctx.is_superadmin:
            return True

        # Walk user_roles → roles → role_permissions → actions and ask whether
        # any role assigned to this user grants the target action (Req 5.3,
        # 6.1). Read on this request so revocation is immediate (Req 6.4).
        grant = (
            select(RolePermission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .join(Action, Action.id == RolePermission.action_id)
            .where(
                UserRole.user_id == ctx.user_id,
                Action.action_key == action_key,
            )
        )

        # Respect custom-role customer scoping when acting under a custom role:
        # only assignments bound to that customer count, preventing a grant in
        # one customer from authorizing an action in another.
        if ctx.custom_role_customer_id is not None:
            grant = grant.where(
                UserRole.customer_id == ctx.custom_role_customer_id
            )

        try:
            result = await self._session.execute(select(exists(grant)))
            return bool(result.scalar())
        except SQLAlchemyError as exc:
            # Req 6.3 — a permission that cannot be read is denied, not assumed.
            raise NotAuthorizedError(
                details={"action_key": action_key},
            ) from exc

    # ------------------------------------------------------------------
    # Tenant context derivation (Task 13.1 — Req 9.1, 4.2, 4.3, 4.5,
    # 9.3, 9.4, 9.5, 9.6, 9.8)
    # ------------------------------------------------------------------

    async def build_tenant_context(
        self,
        claims: AccessTokenClaims,
        impersonation: object | None = None,
        *,
        custom_role_customer_id: UUID | None = None,
    ) -> TenantContext:
        """Derive the immutable per-request tenant scope for ``claims`` (Req 9.1).

        The accessible agency/customer scope is derived from the authenticated
        user's ``role_type`` and their assignments, matching the design's scope
        table:

        * **superadmin** — no tenant boundary: ``is_superadmin=True``,
          ``customer_scope`` empty (meaning "no filter"), ``agency_scope=None``
          (Req 4.2, 9.3).
        * **agencyadmin** — scoped to exactly one Agency: ``agency_scope`` is the
          user's ``agency_id`` and ``customer_scope`` is every Customer under
          that Agency, resolved via :meth:`resolve_agency_customer_ids`
          (cache-backed, Req 4.3, 9.4, 10).
        * **customeradmin** — scoped to the set of Customers assigned via the
          ``customer_users`` mapping, which may span multiple Agencies;
          ``agency_scope=None`` (Req 4.5, 9.5).
        * **custom role** — when the principal acts under a custom role
          (``custom_role_customer_id`` supplied), scope collapses to that single
          Customer and ``custom_role_customer_id`` is recorded on the context
          (Req 9.6).

        Impersonation is deferred to Task 18: the ``impersonation`` parameter is
        accepted so the middleware can pass an impersonation state later without
        changing this signature, but it is not interpreted here — this task only
        builds the non-impersonation context. When ``impersonation`` is provided
        it is ignored (impersonation enforcement is wired in Task 18.1).

        Parameters
        ----------
        claims:
            The decoded, validated access-token claims identifying the acting
            user, their ``role_type``, and (for agencyadmin) their ``agency_id``.
        impersonation:
            Reserved extension point for the active impersonation state
            (Task 18). Ignored by this task; defaults to ``None``.
        custom_role_customer_id:
            When the principal is acting under a custom role, the single Customer
            that role is scoped to. Collapses the derived scope to that Customer
            (Req 9.6).

        Returns
        -------
        TenantContext
            The immutable scope snapshot for this request.

        Raises
        ------
        TenantContextMissingError
            When a non-superadmin scope cannot be derived — an agencyadmin
            without an ``agency_id``, an unknown ``role_type``, or a
            customeradmin/custom-role principal with no accessible Customer
            (Req 9.8).
        """
        role_type = claims.role_type

        # Req 4.2, 9.3 — a superadmin has no tenant boundary. The empty
        # customer_scope is interpreted downstream as "no filter".
        if role_type == "superadmin":
            return TenantContext(
                user_id=claims.sub,
                role_type=role_type,
                agency_scope=None,
                customer_scope=frozenset(),
                is_superadmin=True,
                impersonating=False,
                impersonated_agency_id=None,
                impersonated_customer_id=None,
                impersonator_user_id=None,
                custom_role_customer_id=None,
            )

        # Req 9.6 — acting under a custom role collapses scope to its single
        # Customer regardless of the underlying role_type's broader scope.
        if custom_role_customer_id is not None:
            return TenantContext(
                user_id=claims.sub,
                role_type=role_type,
                agency_scope=None,
                customer_scope=frozenset({custom_role_customer_id}),
                is_superadmin=False,
                impersonating=False,
                impersonated_agency_id=None,
                impersonated_customer_id=None,
                impersonator_user_id=None,
                custom_role_customer_id=custom_role_customer_id,
            )

        if role_type == "agencyadmin":
            agency_id = claims.agency_id
            if agency_id is None:
                # Req 9.8 — an agencyadmin with no Agency has no derivable
                # scope; reject rather than defaulting to an empty (or wide)
                # boundary.
                raise TenantContextMissingError(
                    details={
                        "reason": "agencyadmin_missing_agency",
                        "user_id": str(claims.sub),
                    },
                )
            customer_ids = await self.resolve_agency_customer_ids(agency_id)
            # Req 9.8 — an Agency with zero Customers still yields a valid,
            # if empty, boundary: the agencyadmin is legitimately scoped to its
            # single Agency, so agency_scope alone is sufficient to derive a
            # context. The empty customer_scope simply matches no customer rows.
            return TenantContext(
                user_id=claims.sub,
                role_type=role_type,
                agency_scope=agency_id,
                customer_scope=frozenset(customer_ids),
                is_superadmin=False,
                impersonating=False,
                impersonated_agency_id=None,
                impersonated_customer_id=None,
                impersonator_user_id=None,
                custom_role_customer_id=None,
            )

        if role_type == "customeradmin":
            customer_ids = await self._resolve_customeradmin_customer_ids(
                claims.sub
            )
            if not customer_ids:
                # Req 4.5 / 9.8 — a customeradmin requires at least one assigned
                # Customer; with none, no scope can be derived and the request
                # is rejected.
                raise TenantContextMissingError(
                    details={
                        "reason": "customeradmin_no_customers",
                        "user_id": str(claims.sub),
                    },
                )
            return TenantContext(
                user_id=claims.sub,
                role_type=role_type,
                agency_scope=None,
                customer_scope=frozenset(customer_ids),
                is_superadmin=False,
                impersonating=False,
                impersonated_agency_id=None,
                impersonated_customer_id=None,
                impersonator_user_id=None,
                custom_role_customer_id=None,
            )

        # Req 9.8 — an unrecognized role_type cannot be scoped; fail-closed.
        raise TenantContextMissingError(
            details={
                "reason": "unknown_role_type",
                "role_type": str(role_type),
                "allowed": list(ROLE_TYPES),
            },
        )

    def _get_customer_list_cache(self) -> AgencyCustomerListCache:
        """Return the agency customer-list cache, creating the default lazily.

        The shared Redis-backed cache is only constructed on first use so a
        service that never resolves an agencyadmin scope does not touch Redis.
        Tests inject a fake via the constructor.
        """
        if self._customer_list_cache is None:
            self._customer_list_cache = get_agency_customer_list_cache()
        return self._customer_list_cache

    async def resolve_agency_customer_ids(self, agency_id: UUID) -> list[UUID]:
        """Return every Customer id under ``agency_id`` via cache + DB fallback.

        Resolution goes through the 24-hour Redis cache (Req 10): on a cache hit
        the cached list is returned without querying the database (Req 10.2); on
        a miss/expired key the list is loaded from the database
        (:meth:`_load_agency_customer_ids`) and stored back in the cache with the
        24h TTL before being returned (Req 10.3 store-on-miss, Req 10.1).

        Cache invalidation on customer lifecycle changes is Task 15.2; this
        method only implements the read/store path.
        """
        cache = self._get_customer_list_cache()
        return await cache.resolve(agency_id, lambda: self._load_agency_customer_ids(agency_id))

    async def invalidate_agency_customer_cache(self, agency_id: UUID) -> None:
        """Invalidate the cached accessible-customer list for ``agency_id`` (Req 10.4, 10.5).

        Called whenever a Customer is added to, removed from, suspended within,
        or activated within the Agency so the stale cached list is deleted; the
        next :meth:`resolve_agency_customer_ids` then repopulates from the
        database (Req 10.5). Delegates to the cache's ``invalidate`` primitive
        (Task 15.1).

        This is the design's named entry point (design "Components and
        Interfaces → Authorization_Service"). The wiring that guarantees the
        delete lands within 5 seconds of the change being committed lives in
        :mod:`app.cache.customer_cache_invalidation`, whose post-commit event
        listener detects the affected agencies and calls this method (or the
        module-level lifecycle helpers) after the transaction is durable.
        """
        cache = self._get_customer_list_cache()
        await cache.invalidate(agency_id)

    async def _load_agency_customer_ids(self, agency_id: UUID) -> list[UUID]:
        """Load the ids of every Customer under ``agency_id`` from the DB (Req 9.4).

        The authoritative database read used as the cache loader/fallback in
        :meth:`resolve_agency_customer_ids`. Isolated so the query is the single
        source of truth on a cache miss.
        """
        rows = (
            await self._session.execute(
                select(Customer.id).where(Customer.agency_id == agency_id)
            )
        ).scalars().all()
        return list(rows)

    async def _resolve_customeradmin_customer_ids(
        self, user_id: UUID
    ) -> list[UUID]:
        """Return the ids of Customers assigned to a customeradmin (Req 9.5).

        Resolves the ``customer_users`` mapping for ``user_id``; the assigned
        Customers may belong to different Agencies (Req 4.5). Read on this
        request so newly added/removed assignments take effect immediately.
        """
        rows = (
            await self._session.execute(
                select(CustomerUser.customer_id).where(
                    CustomerUser.user_id == user_id
                )
            )
        ).scalars().all()
        return list(rows)

    async def is_module_usable(
        self, customer_id: UUID, module_id: UUID
    ) -> bool:
        """Return whether ``module_id`` is currently usable for ``customer_id``.

        A Module's SubModules, Resources, and Actions are usable for a Customer
        only when that Customer holds a subscription to the Module that is both
        **active** and **unexpired** (Req 8.1)::

            status == 'active' AND (expires_at IS NULL OR expires_at > now())

        ``expires_at`` being ``NULL`` means the subscription never expires. The
        check is read from the database on **this** request and nothing is
        cached, so adding a Module makes it usable immediately (Req 8.4) and
        removing or expiring a Module makes it non-usable on every subsequent
        request — including requests made under Access_Token sessions issued
        before the change (Req 8.5).

        The enforcement dependency (:func:`app.api.deps.require_permission`)
        calls this per request and rejects the action with
        ``module_not_subscribed`` when it returns ``False`` (Req 8.2).

        Parameters
        ----------
        customer_id:
            The effective Customer the request acts within.
        module_id:
            The Module owning the Action being attempted.

        Returns
        -------
        bool
            ``True`` when a usable (active, unexpired) subscription exists,
            ``False`` when the subscription is absent, inactive, expired, or
            cannot be read (fail-closed — an unreadable subscription is treated
            as non-usable rather than assumed usable).
        """
        # An unresolved module id cannot be gated to a usable subscription;
        # fail-closed to non-usable rather than granting access.
        if module_id is None or customer_id is None:
            return False

        # Load the (at most one) subscription row for this (customer, module)
        # pair on this request. status/expires_at are evaluated in Python
        # against the injectable clock so expiry is deterministic in tests and
        # independent of DB-server time.
        stmt = select(
            CustomerSubscription.status,
            CustomerSubscription.expires_at,
        ).where(
            CustomerSubscription.customer_id == customer_id,
            CustomerSubscription.module_id == module_id,
        )

        try:
            row = (await self._session.execute(stmt)).first()
        except SQLAlchemyError:
            # Fail-closed (Req 8.2 semantics): a subscription that cannot be
            # read is treated as non-usable, never assumed usable.
            return False

        if row is None:
            # No subscription → module not present → non-usable (Req 8.1, 8.2).
            return False

        status, expires_at = row
        if status != "active":
            return False
        if expires_at is None:
            # NULL expiry means "no expiry" → usable while active (Req 8.1).
            return True

        now = self._now()
        # Normalize a naive stored timestamp to UTC so the comparison against
        # the timezone-aware clock never raises.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
        return expires_at > now

    # ------------------------------------------------------------------
    # Custom role management (Task 11.1 — Req 7.2, 7.3, 7.4)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_role_name(name: str) -> str:
        """Validate and normalize a custom-role name (Req 7.2).

        Names are trimmed of surrounding whitespace and must be 1–100
        characters after trimming. Anything else raises :class:`ValidationError`
        so the frontend can surface a precise message.

        Raises
        ------
        ValidationError
            When ``name`` is not a string, or its trimmed length falls outside
            the 1–100 character bound.
        """
        if not isinstance(name, str):
            raise ValidationError(
                "Role name must be a string.",
                details={"field": "name"},
            )
        normalized = name.strip()
        if not (_ROLE_NAME_MIN_LEN <= len(normalized) <= _ROLE_NAME_MAX_LEN):
            raise ValidationError(
                "Role name must be between 1 and 100 characters.",
                details={
                    "field": "name",
                    "min_length": _ROLE_NAME_MIN_LEN,
                    "max_length": _ROLE_NAME_MAX_LEN,
                },
            )
        return normalized

    async def _assert_name_available(
        self,
        customer_id: UUID,
        name: str,
        *,
        exclude_role_id: UUID | None = None,
    ) -> None:
        """Ensure ``name`` is free within ``customer_id`` (Req 7.2).

        Custom-role names are unique per customer. ``exclude_role_id`` lets a
        rename keep its own current name (the row being updated is ignored).

        Raises
        ------
        RoleNameConflictError
            When another custom role in the same customer already uses ``name``.
        """
        stmt = select(Role.id).where(
            Role.is_custom.is_(True),
            Role.customer_id == customer_id,
            Role.name == name,
        )
        if exclude_role_id is not None:
            stmt = stmt.where(Role.id != exclude_role_id)
        existing = (await self._session.execute(stmt)).first()
        if existing is not None:
            raise RoleNameConflictError(
                details={"customer_id": str(customer_id), "name": name},
            )

    async def _get_custom_role(
        self, role_id: UUID, customer_id: UUID
    ) -> Role:
        """Load a custom role scoped to ``customer_id`` (Req 7.3).

        Operations are scoped to the customer: a role is only visible when it is
        a custom role belonging to that customer. Anything else (fixed role,
        another customer's role, unknown id) is treated as not found and denied
        so a caller cannot reach across the tenant boundary.

        Raises
        ------
        NotAuthorizedError
            When no custom role with ``role_id`` exists within ``customer_id``.
        """
        stmt = select(Role).where(
            Role.id == role_id,
            Role.is_custom.is_(True),
            Role.customer_id == customer_id,
        )
        role = (await self._session.execute(stmt)).scalar_one_or_none()
        if role is None:
            raise NotAuthorizedError(
                details={
                    "role_id": str(role_id),
                    "customer_id": str(customer_id),
                },
            )
        return role

    async def create_custom_role(
        self, ctx: TenantContext, customer_id: UUID, name: str
    ) -> Role:
        """Create a new custom role scoped to ``customer_id`` (Req 7.2, 7.3).

        The role is created with ``is_custom=True`` and bound to the single
        customer. The name is validated for length (1–100 chars) and uniqueness
        within the customer before insert.

        Parameters
        ----------
        ctx:
            The acting principal's tenant context. The operation is scoped to
            ``customer_id`` (Req 7.3); caller-level access enforcement lives in
            the router.
        customer_id:
            The customer the new custom role belongs to.
        name:
            The desired role name (1–100 characters, unique within the
            customer).

        Returns
        -------
        Role
            The persisted custom role (flushed so ``id`` is populated).

        Raises
        ------
        ValidationError
            When the name length is out of bounds.
        RoleNameConflictError
            When the name already exists within the customer.
        """
        normalized = self._normalize_role_name(name)
        await self._assert_name_available(customer_id, normalized)

        role = Role(
            role_type=None,
            is_custom=True,
            customer_id=customer_id,
            name=normalized,
        )
        self._session.add(role)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # A concurrent insert may win the unique(customer_id, name) race;
            # surface it as the same conflict error rather than a 500.
            await self._session.rollback()
            raise RoleNameConflictError(
                details={"customer_id": str(customer_id), "name": normalized},
            ) from exc
        return role

    async def clone_custom_role(
        self, ctx: TenantContext, source_role_id: UUID, new_name: str
    ) -> Role:
        """Clone a custom role, copying its Action set (Req 7.4).

        Creates a new custom role in the same customer as the source, with a
        name that is unique within that customer, and copies every
        ``RolePermission`` (Action grant) from the source. The caller may
        subsequently add or remove Actions from the copied set (Task 11.2).

        The source is resolved within the acting customer scope so a clone
        cannot copy another tenant's role.

        Parameters
        ----------
        ctx:
            The acting principal's tenant context supplying the customer scope
            (``custom_role_customer_id`` when acting under a custom role,
            otherwise the single ``customer_scope`` entry).
        source_role_id:
            The custom role to copy.
        new_name:
            The name for the cloned role (1–100 characters, unique within the
            customer).

        Returns
        -------
        Role
            The persisted clone with its copied Action set.

        Raises
        ------
        ValidationError
            When ``new_name`` length is out of bounds.
        NotAuthorizedError
            When the source role is not a custom role within the caller's
            customer scope.
        RoleNameConflictError
            When ``new_name`` already exists within the customer.
        """
        normalized = self._normalize_role_name(new_name)
        customer_id = self._require_single_customer_scope(ctx)
        source = await self._get_custom_role(source_role_id, customer_id)

        await self._assert_name_available(customer_id, normalized)

        clone = Role(
            role_type=None,
            is_custom=True,
            customer_id=source.customer_id,
            name=normalized,
        )
        self._session.add(clone)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise RoleNameConflictError(
                details={
                    "customer_id": str(customer_id),
                    "name": normalized,
                },
            ) from exc

        # Copy the source role's Action set (Req 7.4). Read distinct action_ids
        # and insert a fresh role_permissions row per action for the clone.
        action_rows = (
            await self._session.execute(
                select(RolePermission.action_id).where(
                    RolePermission.role_id == source.id
                )
            )
        ).scalars().all()
        for action_id in action_rows:
            self._session.add(
                RolePermission(role_id=clone.id, action_id=action_id)
            )
        await self._session.flush()
        return clone

    async def _resolve_action_modules(
        self, action_ids: list[UUID]
    ) -> dict[UUID, UUID]:
        """Map each Action id to its owning Module id (Req 7.5, 7.6).

        Walks the permission graph ``actions → resources → submodules`` so the
        subscription gate can be evaluated per Action against its parent
        Module. Only ids that resolve to an existing Action are returned; an
        unknown Action id is simply absent from the result and treated as
        non-assignable by the caller.

        Parameters
        ----------
        action_ids:
            The distinct Action ids to resolve.

        Returns
        -------
        dict[UUID, UUID]
            A mapping from ``action_id`` to ``module_id``.
        """
        if not action_ids:
            return {}
        stmt = (
            select(Action.id, SubModule.module_id)
            .join(Resource, Resource.id == Action.resource_id)
            .join(SubModule, SubModule.id == Resource.submodule_id)
            .where(Action.id.in_(action_ids))
        )
        rows = (await self._session.execute(stmt)).all()
        return {action_id: module_id for action_id, module_id in rows}

    async def assign_actions(
        self,
        ctx: TenantContext,
        role_id: UUID,
        action_ids: list[UUID],
    ) -> Role:
        """Set a custom role's Action grants, gated by subscription (Req 7.5–7.9).

        The role's ``role_permissions`` set is replaced with ``action_ids``,
        but only Actions whose parent Module is **currently subscribed** for the
        role's Customer may be *newly* assigned (Req 7.5). Module ownership is
        resolved through the ``actions → resources → submodules`` graph and each
        distinct Module is checked with :meth:`is_module_usable`.

        Atomicity of rejection (Req 7.6, 7.9): if *any* requested Action either
        cannot be resolved to a Module or belongs to a Module that is not
        currently usable, the whole assignment is rejected with
        :class:`ActionModuleUnsubscribedError` and the role's **existing**
        Actions are left entirely unchanged.

        Retention of removed/expired modules (Req 7.7, 7.8, 8.6): this operation
        only admits currently-subscribed Modules for newly assigned Actions. It
        does **not** strip previously-recorded Actions whose Module has since
        been removed or expired — those rows are retained in the definition and
        simply evaluate as non-usable at enforcement time via the module gate,
        so they are restored to usability when the Module is re-added. In
        practice a caller wishing to preserve such rows includes them in
        ``action_ids``; because their Module is unsubscribed they would be
        rejected, so retention is achieved by leaving the definition untouched
        on rejection rather than by silently dropping them.

        Parameters
        ----------
        ctx:
            The acting principal's tenant context supplying the single customer
            scope the role is bound to.
        role_id:
            The custom role whose Action set is being assigned.
        action_ids:
            The desired set of Action ids for the role. Duplicates are
            collapsed. An empty list clears all currently-usable grants (subject
            to the retention note above).

        Returns
        -------
        Role
            The role with its updated Action set.

        Raises
        ------
        NotAuthorizedError
            When the role is not a custom role within the caller's customer
            scope.
        ActionModuleUnsubscribedError
            When any requested Action's Module is absent/unresolvable or not
            currently subscribed; the role's existing Actions are unchanged.
        """
        customer_id = self._require_single_customer_scope(ctx)
        role = await self._get_custom_role(role_id, customer_id)

        # Collapse duplicates while preserving determinism of the checks.
        requested: list[UUID] = list(dict.fromkeys(action_ids))

        # Resolve every requested Action to its owning Module up front so the
        # subscription gate can reject the whole assignment atomically before
        # any grant is mutated (Req 7.6, 7.9).
        action_to_module = await self._resolve_action_modules(requested)

        # Cache per-module usability so each distinct Module is checked once.
        module_usable: dict[UUID, bool] = {}
        for action_id in requested:
            module_id = action_to_module.get(action_id)
            if module_id is None:
                # An Action that does not resolve to a Module (unknown id, or a
                # broken graph) cannot be gated to a subscription; reject the
                # whole assignment, leaving existing Actions unchanged.
                raise ActionModuleUnsubscribedError(
                    details={
                        "role_id": str(role_id),
                        "action_id": str(action_id),
                    },
                )
            if module_id not in module_usable:
                module_usable[module_id] = await self.is_module_usable(
                    customer_id, module_id
                )
            if not module_usable[module_id]:
                # Req 7.6 / 7.9 — an Action from an unsubscribed Module is
                # rejected and the role's existing Actions are left unchanged.
                raise ActionModuleUnsubscribedError(
                    details={
                        "role_id": str(role_id),
                        "action_id": str(action_id),
                        "module_id": str(module_id),
                    },
                )

        # All requested Actions belong to currently-usable Modules. Reconcile
        # the role's grants to exactly the requested set: add the missing ones
        # and remove the now-unwanted ones.
        existing_grants = (
            await self._session.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id
                )
            )
        ).scalars().all()
        existing_by_action = {g.action_id: g for g in existing_grants}

        requested_set = set(requested)
        # Add newly requested grants.
        for action_id in requested:
            if action_id not in existing_by_action:
                self._session.add(
                    RolePermission(role_id=role.id, action_id=action_id)
                )
        # Remove grants no longer requested.
        for action_id, grant in existing_by_action.items():
            if action_id not in requested_set:
                await self._session.delete(grant)

        await self._session.flush()
        return role

    async def update_custom_role(
        self,
        ctx: TenantContext,
        role_id: UUID,
        *,
        name: str | None = None,
    ) -> Role:
        """Rename a custom role within the caller's customer (Req 7.3).

        Only the name is editable here (Action assignment is Task 11.2). The new
        name is validated for length and uniqueness within the customer,
        ignoring the role's own current name.

        Parameters
        ----------
        ctx:
            The acting principal's tenant context supplying the customer scope.
        role_id:
            The custom role to update.
        name:
            The new name. When ``None`` the name is left unchanged.

        Returns
        -------
        Role
            The updated custom role.

        Raises
        ------
        ValidationError
            When the new name length is out of bounds.
        NotAuthorizedError
            When the role is not a custom role within the caller's customer
            scope.
        RoleNameConflictError
            When the new name already exists within the customer.
        """
        customer_id = self._require_single_customer_scope(ctx)
        role = await self._get_custom_role(role_id, customer_id)

        if name is not None:
            normalized = self._normalize_role_name(name)
            if normalized != role.name:
                await self._assert_name_available(
                    customer_id, normalized, exclude_role_id=role.id
                )
                role.name = normalized
                try:
                    await self._session.flush()
                except IntegrityError as exc:
                    await self._session.rollback()
                    raise RoleNameConflictError(
                        details={
                            "customer_id": str(customer_id),
                            "name": normalized,
                        },
                    ) from exc
        return role

    async def delete_custom_role(
        self, ctx: TenantContext, role_id: UUID
    ) -> None:
        """Delete a custom role within the caller's customer (Req 7.3).

        The role's Action grants (``role_permissions``) are removed alongside
        the role so no orphaned grants remain. The role is resolved within the
        caller's customer scope so a delete cannot reach another tenant's role.

        Parameters
        ----------
        ctx:
            The acting principal's tenant context supplying the customer scope.
        role_id:
            The custom role to delete.

        Raises
        ------
        NotAuthorizedError
            When the role is not a custom role within the caller's customer
            scope.
        """
        customer_id = self._require_single_customer_scope(ctx)
        role = await self._get_custom_role(role_id, customer_id)

        # Remove the role's Action grants first so no orphaned role_permissions
        # rows survive the role deletion.
        grants = (
            await self._session.execute(
                select(RolePermission).where(RolePermission.role_id == role.id)
            )
        ).scalars().all()
        for grant in grants:
            await self._session.delete(grant)

        await self._session.delete(role)
        await self._session.flush()

    @staticmethod
    def _require_single_customer_scope(ctx: TenantContext) -> UUID:
        """Resolve the single customer a custom-role op is scoped to (Req 7.3).

        Custom roles belong to exactly one customer, so an operation must target
        exactly one customer. The scope is taken from ``custom_role_customer_id``
        when acting under a custom role, otherwise from a single-entry
        ``customer_scope``. A superadmin without a customer scope, or any
        principal whose scope is empty or ambiguous, is rejected fail-closed.

        Raises
        ------
        NotAuthorizedError
            When a single customer scope cannot be determined.
        """
        if ctx.custom_role_customer_id is not None:
            return ctx.custom_role_customer_id
        scope = ctx.customer_scope
        if scope is not None and len(scope) == 1:
            return next(iter(scope))
        raise NotAuthorizedError(
            details={"reason": "custom_role_customer_scope_unresolved"},
        )


__all__ = ["AuthorizationService"]

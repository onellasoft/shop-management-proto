"""FastAPI dependencies for per-route authorization enforcement.

This module exposes :func:`require_permission`, the per-route enforcement
dependency described in design "Permission Evaluation & Enforcement". It runs
*after* the auth/tenant middleware has attached the immutable
:class:`~app.core.tenant_context.TenantContext` to ``request.state`` and gates
a route on three checks, in order:

1. **Permission check (fail-closed)** — reads the grant for ``action_key`` from
   the database on this request via
   :meth:`AuthorizationService.has_permission`. A superadmin bypasses the check
   (Req 4.2); any principal without the grant is rejected with
   :class:`NotAuthorizedError` (Req 6.2). If the permission cannot be read, the
   request is denied fail-closed (Req 6.3) — ``has_permission`` already raises
   :class:`NotAuthorizedError` on DB read errors, and this dependency also
   treats any unexpected error from the check as a denial.

2. **Module subscription gate** — rejects actions whose module is not usable
   (unsubscribed or expired) for the effective customer scope (Req 8.2). The
   ``is_module_usable`` method lands in task 10.2; until it exists this gate is
   a no-op guarded by :func:`hasattr`, so task 10.2 only needs to add the
   service method for the gate to activate. See the ``# TODO(task 10.2)`` note.

3. **Sensitive-action gate under impersonation** — while impersonating, a
   sensitive Action (``Action.is_sensitive``) is rejected with
   :class:`ActionRestrictedDuringImpersonationError` (Req 13.2). Task 18.2
   finalizes this alongside the impersonation middleware; a basic version lives
   here so the gate is present as soon as impersonation context is available.

On success the dependency returns the :class:`TenantContext` so routes can
depend on the check *and* receive the context in one call::

    @router.post("/things")
    async def create_thing(
        ctx: TenantContext = Depends(require_permission("inventory.items.things.create")),
    ):
        ...

Design reference: "Permission Evaluation & Enforcement" and the
"Permission-Check Sequence" diagram.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ActionRestrictedDuringImpersonationError,
    ModuleNotSubscribedError,
    NotAuthorizedError,
    TenantContextMissingError,
)
from app.core.tenant_context import TenantContext
from app.db.session import get_db
from app.models.permission import Action, Resource, SubModule
from app.models.user import User
from app.services.authorization_service import AuthorizationService


def _load_tenant_context(request: Request) -> TenantContext:
    """Return the :class:`TenantContext` attached by the auth/tenant middleware.

    The middleware (task 13.2) sets ``request.state.tenant_context`` for every
    authenticated request. If it is absent — e.g. the route was reached without
    a valid context — the request is denied rather than defaulting to broad
    access (fail-closed, Req 9.8).
    """
    ctx: TenantContext | None = getattr(request.state, "tenant_context", None)
    if ctx is None:
        raise TenantContextMissingError()
    return ctx


async def _load_action(db: AsyncSession, action_key: str) -> Action:
    """Load the :class:`Action` (with its module id) for ``action_key``.

    Walks the denormalized ``action_key`` to a single Action and resolves the
    owning module id via the resource → submodule chain, which the module gate
    needs. Fail-closed: an unknown key or a read error denies the request
    (Req 6.2, 6.3).
    """
    stmt = (
        select(Action, SubModule.module_id)
        .join(Resource, Resource.id == Action.resource_id)
        .join(SubModule, SubModule.id == Resource.submodule_id)
        .where(Action.action_key == action_key)
    )
    try:
        row = (await db.execute(stmt)).first()
    except SQLAlchemyError as exc:  # fail-closed on read error (Req 6.3)
        raise NotAuthorizedError(details={"action_key": action_key}) from exc

    if row is None:  # unknown action → deny (Req 6.2)
        raise NotAuthorizedError(details={"action_key": action_key})

    action, module_id = row
    # Stash the resolved module id on the instance so the module gate can use it
    # without re-querying, regardless of relationship loading state.
    action.__dict__["_module_id"] = module_id
    return action


def _effective_customer_id(ctx: TenantContext):
    """Best-effort resolution of the single customer the request acts within.

    The module gate is per-customer, so it only applies when the request is
    scoped to exactly one customer. Superadmin/platform scope has no single
    customer and is not module-gated here.

    This intentionally avoids depending on helper attributes that later tasks
    (13.1 context builder) may add; it derives the effective customer from the
    fields already present on :class:`TenantContext`:

    * under impersonation of a customer, the impersonated customer;
    * when acting under a custom role, that role's single customer;
    * otherwise, the sole customer in ``customer_scope`` if there is exactly one.
    """
    if ctx.impersonating and ctx.impersonated_customer_id is not None:
        return ctx.impersonated_customer_id
    if ctx.custom_role_customer_id is not None:
        return ctx.custom_role_customer_id
    if len(ctx.customer_scope) == 1:
        return next(iter(ctx.customer_scope))
    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return the authenticated :class:`User` for the current request.

    Reads the :class:`TenantContext` attached by the auth/tenant middleware
    (via :func:`_load_tenant_context`, which fails closed with
    :class:`TenantContextMissingError` when no context is present, Req 9.8) and
    loads the matching ``users`` row by ``tenant_context.user_id``.

    Unlike :func:`require_permission`, this dependency performs *no* module/
    permission gating — it only resolves the acting identity. It is used by the
    impersonation router (Task 17.3), where the impersonator is always the
    **authenticated** user (never an already-impersonated context): the
    ``user_id`` on the context is the real signed-in user, so loading it here
    gives the impersonator's own :class:`User` for
    :meth:`ImpersonationService.start` (which reads ``.id``, ``.role_type`` and
    ``.agency_id``).

    Raises
    ------
    TenantContextMissingError
        When the request carries no tenant context (unauthenticated), reusing
        the fail-closed pattern from :func:`_load_tenant_context` (Req 9.8).
    """
    ctx = _load_tenant_context(request)
    user = await db.get(User, ctx.user_id)
    if user is None:
        # A valid context whose user row is gone (e.g. deleted mid-session) is
        # treated as an unresolvable identity and denied fail-closed.
        raise TenantContextMissingError(
            details={"reason": "user_not_found", "user_id": str(ctx.user_id)}
        )
    return user


def require_permission(
    action_key: str,
) -> Callable[..., Awaitable[TenantContext]]:
    """Build a FastAPI dependency enforcing ``action_key`` on a route.

    The returned coroutine dependency runs the permission check, the module
    subscription gate, and the sensitive-action gate (in that order) and
    returns the :class:`TenantContext` on success.

    Parameters
    ----------
    action_key:
        The denormalized ``module.submodule.resource.action`` key of the
        Action the route performs.

    Returns
    -------
    Callable
        An async dependency ``(request, db) -> TenantContext``.
    """

    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> TenantContext:
        ctx = _load_tenant_context(request)
        authz = AuthorizationService(db)
        action = await _load_action(db, action_key)

        # 1. Permission check (fail-closed). has_permission raises
        #    NotAuthorizedError on DB read errors (Req 6.3); guard here as well
        #    so any unexpected failure is a denial rather than a leak.
        try:
            allowed = await authz.has_permission(ctx, action_key)
        except NotAuthorizedError:
            raise
        except Exception as exc:  # defense-in-depth fail-closed (Req 6.3)
            raise NotAuthorizedError(details={"action_key": action_key}) from exc
        if not (ctx.is_superadmin or allowed):
            raise NotAuthorizedError(details={"action_key": action_key})  # Req 6.2

        # 2. Module subscription gate (Req 8.2). Applies only to a single
        #    effective customer; superadmin/platform scope is not gated.
        #    TODO(task 10.2): AuthorizationService.is_module_usable(customer_id,
        #    module_id) will be implemented in task 10.2. Until then this gate
        #    is a no-op guarded by hasattr, so wiring 10.2 requires only adding
        #    the service method — no change to this dependency's structure.
        customer_id = _effective_customer_id(ctx)
        if customer_id is not None and hasattr(authz, "is_module_usable"):
            module_id = action.__dict__.get("_module_id")
            usable = await authz.is_module_usable(customer_id, module_id)
            if not usable:
                raise ModuleNotSubscribedError(
                    details={"action_key": action_key}
                )  # Req 8.2

        # 3. Sensitive-action gate under impersonation (Req 13.2). Basic version;
        #    task 18.2 finalizes this alongside the impersonation middleware.
        if ctx.impersonating and action.is_sensitive:
            raise ActionRestrictedDuringImpersonationError(
                details={"action_key": action_key}
            )  # Req 13.2

        return ctx

    return _dep


__all__ = ["require_permission", "get_current_user"]

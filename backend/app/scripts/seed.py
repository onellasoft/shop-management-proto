"""Idempotent development seed script.

Populates the *existing* backend tables with a small, realistic dataset so a
fresh database is immediately usable: an agency, a handful of customers
(businesses), a superadmin, and per-agency/customer admin users with their
fixed system roles assigned, plus a subscription to every seeded module.

Idempotency
-----------
Every insert is guarded by a lookup on a natural key (agency name, customer
(agency, name), user email, the (user, role, customer) tuple, and the
(customer, module) subscription pair). Running the script repeatedly makes no
further changes and never creates duplicates.

Assumptions
-----------
The three fixed system roles (``superadmin`` / ``agencyadmin`` /
``customeradmin``) and the module catalog are already present, seeded by the
Alembic migrations. This script therefore *looks them up* rather than creating
them; run ``alembic upgrade head`` first (the container entrypoint does this
automatically).

Usage
-----
    # inside the backend container / venv
    python -m app.scripts.seed

    # via Docker (one-off), DB reachable over the compose network
    docker compose run --rm backend python -m app.scripts.seed
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.agency import Agency
from app.models.customer import Customer
from app.models.customer_user import CustomerUser
from app.models.permission import Module
from app.models.role import Role, UserRole
from app.models.subscription import CustomerSubscription
from app.models.user import User

logger = logging.getLogger("onella.seed")
logging.basicConfig(level=logging.INFO, format="[seed] %(message)s")


# Default password for every seeded user (development only).
DEFAULT_PASSWORD = "Password123!"

# One agency with a few businesses (customers) under it.
AGENCY_NAME = "Onella Demo Agency"
CUSTOMER_NAMES = [
    "Apex Electronics",
    "Organic Grocers",
    "Nova Fashion Boutique",
    "Decent Pharmacy",
]

# These mobiles intentionally match the quick-login buttons on the dev Login UI
# so the OTP flow is testable without a real phone: request OTP, read the code
# from `docker compose logs backend` (MockSmsSender logs it), enter it in the UI.
SUPERADMIN_EMAIL = "superadmin@onella.test"
SUPERADMIN_MOBILE = "+919561311757"   # "Agency Login" quick-fill on dev Login UI

AGENCYADMIN_EMAIL = "agencyadmin@onella.test"
AGENCYADMIN_MOBILE = "+917588611478"  # "Business Login" quick-fill on dev Login UI

# Maps a customeradmin email+mobile to the customer name they administer.
CUSTOMER_ADMINS = {
    "admin.apex@onella.test": {
        "customer": "Apex Electronics",
        "mobile": "+919876543210",
    },
    "admin.grocers@onella.test": {
        "customer": "Organic Grocers",
        "mobile": "+919123456789",
    },
}


async def _get_or_create_agency(session: AsyncSession, name: str) -> Agency:
    existing = await session.scalar(select(Agency).where(Agency.name == name))
    if existing is not None:
        return existing
    agency = Agency(name=name, status="active")
    session.add(agency)
    await session.flush()
    logger.info("created agency %s (%s)", name, agency.id)
    return agency


async def _get_or_create_customer(
    session: AsyncSession, agency: Agency, name: str
) -> Customer:
    existing = await session.scalar(
        select(Customer).where(
            Customer.agency_id == agency.id, Customer.name == name
        )
    )
    if existing is not None:
        return existing
    customer = Customer(agency_id=agency.id, name=name, status="active")
    session.add(customer)
    await session.flush()
    logger.info("created customer %s (%s)", name, customer.id)
    return customer


async def _get_or_create_user(
    session: AsyncSession,
    *,
    email: str,
    role_type: str,
    mobile: str | None = None,
    agency_id=None,
) -> User:
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        # Backfill mobile if it was added to the seed after the user was first created.
        if mobile is not None and existing.mobile != mobile:
            existing.mobile = mobile
            await session.flush()
        return existing
    user = User(
        email=email,
        mobile=mobile,
        role_type=role_type,
        agency_id=agency_id,
        password_hash=hash_password(DEFAULT_PASSWORD),
        status="active",
    )
    session.add(user)
    await session.flush()
    logger.info("created user %s (%s, %s)", email, role_type, user.id)
    return user


async def _get_fixed_role(session: AsyncSession, role_type: str) -> Role:
    role = await session.scalar(
        select(Role).where(Role.role_type == role_type, Role.is_custom.is_(False))
    )
    if role is None:
        raise RuntimeError(
            f"Fixed role '{role_type}' not found. Run `alembic upgrade head` "
            "before seeding."
        )
    return role


async def _assign_role(
    session: AsyncSession, user: User, role: Role, customer_id=None
) -> None:
    existing = await session.scalar(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
            UserRole.customer_id.is_(None)
            if customer_id is None
            else (UserRole.customer_id == customer_id),
        )
    )
    if existing is not None:
        return
    session.add(
        UserRole(user_id=user.id, role_id=role.id, customer_id=customer_id)
    )
    await session.flush()


async def _link_customer_user(
    session: AsyncSession, user: User, customer: Customer
) -> None:
    existing = await session.scalar(
        select(CustomerUser).where(
            CustomerUser.user_id == user.id,
            CustomerUser.customer_id == customer.id,
        )
    )
    if existing is not None:
        return
    session.add(CustomerUser(user_id=user.id, customer_id=customer.id))
    await session.flush()


async def _subscribe_all_modules(
    session: AsyncSession, customer: Customer
) -> None:
    module_ids = (await session.scalars(select(Module.id))).all()
    for module_id in module_ids:
        existing = await session.scalar(
            select(CustomerSubscription).where(
                CustomerSubscription.customer_id == customer.id,
                CustomerSubscription.module_id == module_id,
            )
        )
        if existing is not None:
            continue
        session.add(
            CustomerSubscription(
                customer_id=customer.id,
                module_id=module_id,
                status="active",
            )
        )
    await session.flush()


async def seed() -> None:
    """Run the full idempotent seed within a single transaction."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            agency = await _get_or_create_agency(session, AGENCY_NAME)

            customers: dict[str, Customer] = {}
            for name in CUSTOMER_NAMES:
                customers[name] = await _get_or_create_customer(
                    session, agency, name
                )

            # Fixed system roles (seeded by migration).
            superadmin_role = await _get_fixed_role(session, "superadmin")
            agencyadmin_role = await _get_fixed_role(session, "agencyadmin")
            customeradmin_role = await _get_fixed_role(session, "customeradmin")

            # Superadmin (no agency scope).
            superadmin = await _get_or_create_user(
                session,
                email=SUPERADMIN_EMAIL,
                mobile=SUPERADMIN_MOBILE,
                role_type="superadmin",
            )
            await _assign_role(session, superadmin, superadmin_role)

            # Agency admin scoped to the demo agency.
            agencyadmin = await _get_or_create_user(
                session,
                email=AGENCYADMIN_EMAIL,
                mobile=AGENCYADMIN_MOBILE,
                role_type="agencyadmin",
                agency_id=agency.id,
            )
            await _assign_role(session, agencyadmin, agencyadmin_role)

            # Customer admins linked to their customer + role assignment.
            for email, info in CUSTOMER_ADMINS.items():
                customer = customers[info["customer"]]
                admin = await _get_or_create_user(
                    session,
                    email=email,
                    mobile=info["mobile"],
                    role_type="customeradmin",
                )
                await _link_customer_user(session, admin, customer)
                await _assign_role(
                    session, admin, customeradmin_role, customer_id=customer.id
                )

            # Every customer gets a subscription to every module.
            for customer in customers.values():
                await _subscribe_all_modules(session, customer)

    logger.info("seed complete")
    logger.info("  superadmin:    %s / %s  (mobile: %s)", SUPERADMIN_EMAIL, DEFAULT_PASSWORD, SUPERADMIN_MOBILE)
    logger.info("  agencyadmin:   %s / %s  (mobile: %s)", AGENCYADMIN_EMAIL, DEFAULT_PASSWORD, AGENCYADMIN_MOBILE)
    for email, info in CUSTOMER_ADMINS.items():
        logger.info("  customeradmin: %s / %s  (mobile: %s)", email, DEFAULT_PASSWORD, info["mobile"])


def main() -> None:
    """Synchronous entry point for ``python -m app.scripts.seed``."""
    asyncio.run(seed())


if __name__ == "__main__":
    main()

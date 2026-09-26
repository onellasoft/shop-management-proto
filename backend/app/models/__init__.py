"""SQLAlchemy ORM models.

Importing this package registers every model on ``Base.metadata`` so Alembic
autogenerate (``alembic/env.py`` imports ``app.models``) can see all tables.
Add new model modules here as they are created.
"""

from app.models.agency import Agency
from app.models.customer import Customer
from app.models.customer_user import CustomerUser
from app.models.impersonation import ImpersonationSession
from app.models.permission import Action, Module, Resource, SubModule
from app.models.refresh_token import RefreshToken
from app.models.role import Role, RolePermission, UserRole
from app.models.subscription import CustomerSubscription
from app.models.user import User

__all__ = [
    "Action",
    "Agency",
    "Customer",
    "CustomerSubscription",
    "CustomerUser",
    "ImpersonationSession",
    "Module",
    "RefreshToken",
    "Resource",
    "Role",
    "RolePermission",
    "SubModule",
    "User",
    "UserRole",
]

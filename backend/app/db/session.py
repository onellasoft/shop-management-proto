"""Async database engine, session factory, and FastAPI dependency.

Uses SQLAlchemy 2.0 async APIs (``create_async_engine`` +
``async_sessionmaker``). The database URL is sourced from the application
``Settings`` defined in ``app.core.config``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# A single async engine is shared process-wide. It manages the connection pool
# to PostgreSQL via the asyncpg driver (e.g. "postgresql+asyncpg://...").
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_pre_ping=True,
    future=True,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
# ``expire_on_commit=False`` keeps attributes accessible after commit, which is
# convenient for returning ORM objects from request handlers.
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# ---------------------------------------------------------------------------
# Agency customer-list cache invalidation (Task 15.2 — Req 10.4, 10.5)
# ---------------------------------------------------------------------------
# Attach the SQLAlchemy post-commit listeners that invalidate an Agency's
# cached accessible-customer list whenever a Customer is added / removed /
# suspended / activated. Registered here (once, at session-layer import) so
# every session created by ``AsyncSessionLocal`` — whose async engine drives an
# underlying sync ``Session`` — participates. Registration is idempotent.
from app.cache.customer_cache_invalidation import (  # noqa: E402
    register_customer_cache_invalidation,
)

register_customer_cache_invalidation()

# ---------------------------------------------------------------------------
# Mutation audit logging (Task 21 — Req 14)
# ---------------------------------------------------------------------------
# Attach the SQLAlchemy listeners that (a) capture create/update/delete of
# audited models and enqueue an audit write after commit (Req 14.1-14.5) and
# (b) reject UPDATE/DELETE of append-only audit logs at flush time (Req 14.6).
# Registered here, once at session-layer import, alongside the customer-cache
# listeners so both coexist on every session. Registration is idempotent.
from app.audit.mutation_capture import register_audit_listeners  # noqa: E402

register_audit_listeners()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a scoped async session per request.

    The session is committed on successful completion of the request handler
    and rolled back if an exception propagates. It is always closed.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


__all__ = [
    "engine",
    "AsyncSessionLocal",
    "get_db",
    "register_customer_cache_invalidation",
    "register_audit_listeners",
]

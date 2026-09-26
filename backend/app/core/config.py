"""Application configuration.

Centralized settings loaded from environment variables (and an optional
``.env`` file) via ``pydantic-settings``. Covers datastore/cache connection
strings, JWT lifecycle parameters, OTP TTL, and the deployment environment
flag that selects the mock SMS provider in development.

References:
- Design "Technology Stack": PostgreSQL primary datastore, Redis cache/ephemeral
  store, PyJWT for tokens.
- Design "JWT Token Structure & Lifecycle":
    * ACCESS_TOKEN_TTL_MIN configurable 15-30 min, default 20 (Req 3.1).
    * REFRESH_TOKEN_TTL_DAYS configurable 7-30 days, default 14 (Req 3.2).
- Requirement 2.1: OTP stored in Redis with a 10-minute (600s) TTL.
- Requirement 2.10: development environment uses a mock SMS service.
"""

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environment flag.

    ``DEVELOPMENT`` selects the mock SMS provider (Req 2.10).
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings sourced from the environment.

    All values may be overridden via environment variables (case-insensitive)
    or an optional ``.env`` file at the backend root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # --- Deployment environment (Req 2.10) ---
    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        description="Deployment environment; 'development' enables the mock SMS provider.",
    )

    # --- Datastores (design Technology Stack) ---
    database_url: str = Field(
        default="postgresql+asyncpg://onella:onella@localhost:5432/onella",
        description="Async SQLAlchemy PostgreSQL connection URL.",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (OTP store, agency customer-list cache, Celery broker).",
    )

    # --- CORS (browser access from the frontend origin) ---
    # Stored as a raw string to avoid pydantic-settings attempting to JSON-parse
    # a list-typed env var. The comma-separated value is split by the
    # ``cors_origins`` property below. Env var: ``CORS_ORIGINS``.
    cors_origins_raw: str = Field(
        default="http://localhost:4300",
        alias="cors_origins",
        description=(
            "Allowed browser origins for CORS as a comma-separated string via "
            "the CORS_ORIGINS env var. Use '*' to allow any origin (dev only)."
        ),
    )

    @property
    def cors_origins(self) -> list[str]:
        """Parsed list of allowed CORS origins (comma-separated in the env)."""
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]

    # --- JWT configuration (design JWT Token Structure & Lifecycle) ---
    jwt_secret: str = Field(
        default="change-me-in-production",
        description="Secret key used to sign/verify JWTs.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm.",
    )
    # Req 3.1: access token expiry configurable 15-30 min, default 20.
    access_token_ttl_min: int = Field(
        default=20,
        ge=15,
        le=30,
        description="Access token time-to-live in minutes (15-30, default 20).",
    )
    # Req 3.2: refresh token expiry configurable 7-30 days, default 14.
    refresh_token_ttl_days: int = Field(
        default=14,
        ge=7,
        le=30,
        description="Refresh token time-to-live in days (7-30, default 14).",
    )

    # --- OTP configuration (Req 2.1) ---
    otp_ttl_seconds: int = Field(
        default=600,
        description="OTP time-to-live in seconds (10 minutes).",
    )

    # --- Agency customer-list cache (Req 10.1, 10.3) ---
    agency_customer_cache_ttl_seconds: int = Field(
        default=86_400,
        description="Agency accessible-customer-list cache TTL in seconds (24 hours).",
    )

    # --- Impersonation session lifecycle (Req 11.7) ---
    impersonation_session_ttl_minutes: int = Field(
        default=60,
        description=(
            "Impersonation session max age in minutes; a session active longer "
            "than this is treated as expired (Req 11.7)."
        ),
    )

    @property
    def is_development(self) -> bool:
        """Whether the deployment environment is development (Req 2.10)."""
        return self.environment == Environment.DEVELOPMENT


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Cached so the environment is parsed once per process. Use FastAPI's
    dependency injection or import this accessor rather than constructing
    ``Settings`` directly.
    """
    return Settings()


# Convenient module-level singleton for non-DI access sites.
settings = get_settings()

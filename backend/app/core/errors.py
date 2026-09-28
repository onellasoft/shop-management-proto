"""Standardized error codes, exception classes, and central FastAPI handlers.

All errors emitted by the application are serialized into a single, machine
readable JSON envelope so the frontend can render precise, localized messages::

    {
        "error": {
            "code": "module_not_subscribed",
            "message": "Human-readable message suitable for display.",
            "details": {"module": "inventory"}
        }
    }

The error codes below mirror the design's "Machine-Readable Error Codes" table.
Authentication-related errors deliberately avoid revealing whether an email or
mobile number exists (non-enumerating), satisfying requirements 1.2 and 2.2.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# HTTP 422. Referenced as a literal because Starlette has deprecated the
# ``HTTP_422_UNPROCESSABLE_ENTITY`` constant in favor of a renamed one; the
# numeric code is stable across versions.
HTTP_422_UNPROCESSABLE = 422


class ErrorCode(str, Enum):
    """Machine-readable error codes returned to clients.

    Values match the design error table exactly so the frontend can key off a
    stable identifier regardless of the human-readable message.
    """

    AUTHENTICATION_ERROR = "authentication_error"
    ACCOUNT_LOCKED = "account_locked"
    OTP_RATE_LIMITED = "otp_rate_limited"
    OTP_EXPIRED = "otp_expired"
    NOT_AUTHORIZED = "not_authorized"
    ACTION_NOT_CREATABLE = "action_not_creatable"
    MODULE_NOT_SUBSCRIBED = "module_not_subscribed"
    ROLE_NAME_CONFLICT = "role_name_conflict"
    ACTION_MODULE_UNSUBSCRIBED = "action_module_unsubscribed"
    TENANT_BOUNDARY_VIOLATION = "tenant_boundary_violation"
    TENANT_CONTEXT_MISSING = "tenant_context_missing"
    IMPERSONATION_ACTIVE = "impersonation_active"
    IMPERSONATION_FORBIDDEN = "impersonation_forbidden"
    ACTION_RESTRICTED_DURING_IMPERSONATION = "action_restricted_during_impersonation"
    INVALID_DATE_RANGE = "invalid_date_range"
    AUDIT_IMMUTABLE = "audit_immutable"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"
    USER_ALREADY_IN_CUSTOMER = "user_already_in_customer"


# ---------------------------------------------------------------------------
# Base exception
# ---------------------------------------------------------------------------


class AppError(Exception):
    """Base class for all application errors mapped to the standard envelope.

    Subclasses set a default ``code``, ``http_status``, and ``message`` but any
    of these can be overridden at raise time. ``details`` carries structured,
    machine-readable context (e.g. ``{"module": "inventory"}``).
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: ErrorCode | None = None,
        http_status: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the standard ``{error:{code,message,details}}`` body."""
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            }
        }


# ---------------------------------------------------------------------------
# Concrete exceptions — one per design error code
# ---------------------------------------------------------------------------


class AuthenticationError(AppError):
    """Bad/expired/invalid credentials or token (non-enumerating).

    Requirements: 1.2, 1.3, 2.2, 3.6, 3.7.
    """

    code = ErrorCode.AUTHENTICATION_ERROR
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "Authentication failed."


class AccountLockedError(AppError):
    """Account locked after 5 failed logins within 15 minutes. Requirement 1.5."""

    code = ErrorCode.ACCOUNT_LOCKED
    http_status = status.HTTP_423_LOCKED
    message = "Account is temporarily locked. Try again later."


class OTPRateLimitedError(AppError):
    """More than 3 OTP requests within 10 minutes. Requirement 2.4."""

    code = ErrorCode.OTP_RATE_LIMITED
    http_status = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many OTP requests. Please wait before trying again."


class OTPExpiredError(AppError):
    """OTP TTL elapsed. Requirement 2.8."""

    code = ErrorCode.OTP_EXPIRED
    http_status = status.HTTP_401_UNAUTHORIZED
    message = "The one-time password has expired."


class NotAuthorizedError(AppError):
    """No permission for action, or permission unreadable (fail-closed).

    Requirements: 6.2, 6.3.
    """

    code = ErrorCode.NOT_AUTHORIZED
    http_status = status.HTTP_403_FORBIDDEN
    message = "You are not authorized to perform this action."


class ActionNotCreatableError(AppError):
    """Attempt to create a globally-defined action. Requirement 5.4."""

    code = ErrorCode.ACTION_NOT_CREATABLE
    http_status = status.HTTP_403_FORBIDDEN
    message = "Actions are globally defined and cannot be created."


class ModuleNotSubscribedError(AppError):
    """Action's module is not subscribed or has expired. Requirement 8.2."""

    code = ErrorCode.MODULE_NOT_SUBSCRIBED
    http_status = status.HTTP_403_FORBIDDEN
    message = "The module for this action is not subscribed or has expired."


class RoleNameConflictError(AppError):
    """Custom role name not unique within the customer. Requirement 7.2."""

    code = ErrorCode.ROLE_NAME_CONFLICT
    http_status = status.HTTP_409_CONFLICT
    message = "A role with this name already exists for this customer."


class ActionModuleUnsubscribedError(AppError):
    """Assigning an action whose module is not subscribed.

    Requirements: 7.6, 7.9.
    """

    code = ErrorCode.ACTION_MODULE_UNSUBSCRIBED
    http_status = status.HTTP_403_FORBIDDEN
    message = "Cannot assign an action from an unsubscribed module."


class TenantBoundaryViolationError(AppError):
    """Data accessed outside the tenant context.

    Requirements: 4.4, 9.7, 12.2.
    """

    code = ErrorCode.TENANT_BOUNDARY_VIOLATION
    http_status = status.HTTP_403_FORBIDDEN
    message = "The requested resource is outside your tenant boundary."


class TenantContextMissingError(AppError):
    """Non-superadmin scope cannot be derived. Requirement 9.8."""

    code = ErrorCode.TENANT_CONTEXT_MISSING
    http_status = status.HTTP_403_FORBIDDEN
    message = "A tenant scope could not be determined for this request."


class ImpersonationActiveError(AppError):
    """An active impersonation session already exists. Requirement 11.6."""

    code = ErrorCode.IMPERSONATION_ACTIVE
    http_status = status.HTTP_409_CONFLICT
    message = "An impersonation session is already active."


class ImpersonationForbiddenError(AppError):
    """Impersonation target is outside the impersonator's scope. Requirement 11.3."""

    code = ErrorCode.IMPERSONATION_FORBIDDEN
    http_status = status.HTTP_403_FORBIDDEN
    message = "You cannot impersonate this tenant."


class ActionRestrictedDuringImpersonationError(AppError):
    """Sensitive action attempted during impersonation. Requirement 13.2."""

    code = ErrorCode.ACTION_RESTRICTED_DURING_IMPERSONATION
    http_status = status.HTTP_403_FORBIDDEN
    message = "This action is not permitted while impersonating."


class InvalidDateRangeError(AppError):
    """Audit query start later than end. Requirement 15.4."""

    code = ErrorCode.INVALID_DATE_RANGE
    http_status = HTTP_422_UNPROCESSABLE
    message = "The start date must not be later than the end date."


class AuditImmutableError(AppError):
    """Attempt to update or delete an audit log. Requirement 14.6."""

    code = ErrorCode.AUDIT_IMMUTABLE
    http_status = status.HTTP_405_METHOD_NOT_ALLOWED
    message = "Audit logs are append-only and cannot be modified or deleted."


class ValidationError(AppError):
    """Request/payload validation failure raised explicitly by services."""

    code = ErrorCode.VALIDATION_ERROR
    http_status = HTTP_422_UNPROCESSABLE
    message = "The request could not be validated."


class UserAlreadyInCustomerError(AppError):
    """User is already a staff member of this customer. Raised during invite."""

    code = ErrorCode.USER_ALREADY_IN_CUSTOMER
    http_status = status.HTTP_409_CONFLICT
    message = "This user is already a staff member of the customer."


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def error_payload(
    code: ErrorCode | str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the standard error envelope from explicit parts."""
    return {
        "error": {
            "code": code.value if isinstance(code, ErrorCode) else code,
            "message": message,
            "details": details or {},
        }
    }


def _json_error(status_code: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


# ---------------------------------------------------------------------------
# Central exception handlers
# ---------------------------------------------------------------------------


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """Map any :class:`AppError` to the standard envelope."""
    return _json_error(exc.http_status, exc.to_dict())


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map FastAPI/Pydantic request validation failures to ``validation_error``."""
    body = error_payload(
        ErrorCode.VALIDATION_ERROR,
        "The request could not be validated.",
        {"errors": exc.errors()},
    )
    return _json_error(HTTP_422_UNPROCESSABLE, body)


async def http_exception_handler(
    _request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Map raw ``HTTPException``s (e.g. 404) into the standard envelope.

    Preserves the original status code while giving the frontend a consistent
    shape. The code is derived from the status where a known mapping exists,
    otherwise a generic ``internal_error`` / status-based label is used.
    """
    code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Request could not be completed."
    details: dict[str, Any] = {} if isinstance(detail, str) else {"detail": detail}
    body = error_payload(code, message, details)
    return _json_error(exc.status_code, body)


async def unhandled_exception_handler(
    _request: Request, _exc: Exception
) -> JSONResponse:
    """Catch-all handler ensuring even unexpected errors use the envelope."""
    body = error_payload(
        ErrorCode.INTERNAL_ERROR,
        "An unexpected error occurred.",
    )
    return _json_error(status.HTTP_500_INTERNAL_SERVER_ERROR, body)


# Best-effort mapping from HTTP status to a stable error code for raw
# HTTPExceptions that don't originate from an AppError.
_STATUS_TO_CODE: dict[int, ErrorCode] = {
    status.HTTP_401_UNAUTHORIZED: ErrorCode.AUTHENTICATION_ERROR,
    status.HTTP_403_FORBIDDEN: ErrorCode.NOT_AUTHORIZED,
    HTTP_422_UNPROCESSABLE: ErrorCode.VALIDATION_ERROR,
}


def register_exception_handlers(app: FastAPI) -> None:
    """Register all central exception handlers on the FastAPI app.

    Call this from the application factory so every route benefits from the
    standardized error envelope.
    """
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

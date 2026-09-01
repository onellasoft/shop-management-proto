"""SMS sender abstraction and environment-based selection.

Defines a provider-agnostic ``SmsSender`` interface used by the Auth_Service to
deliver one-time passwords (OTPs). Two implementations are provided:

- ``MockSmsSender``: records/logs messages instead of contacting a provider.
- ``LiveSmsSender``: placeholder for the real SMS provider integration.

The ``get_sms_sender`` factory selects the mock implementation whenever the
deployment environment is development, satisfying Requirement 2.10 (WHERE the
deployment environment is development, THE Auth_Service SHALL use a mock SMS
service in place of the live SMS provider).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentMessage:
    """An SMS message recorded by the mock sender."""

    mobile: str
    message: str


class SmsSender(ABC):
    """Provider-agnostic SMS sender interface.

    Implementations deliver a text ``message`` to a destination ``mobile``
    number. The method is asynchronous so implementations may perform network
    I/O without blocking the event loop.
    """

    @abstractmethod
    async def send(self, mobile: str, message: str) -> None:
        """Send ``message`` to ``mobile``.

        Raises:
            Exception: implementation-specific delivery failures.
        """
        raise NotImplementedError


class MockSmsSender(SmsSender):
    """In-memory SMS sender for development and testing.

    Instead of contacting a live provider, sent messages are logged and
    appended to :attr:`sent` so callers/tests can assert on delivery.
    """

    def __init__(self) -> None:
        self.sent: list[SentMessage] = []

    async def send(self, mobile: str, message: str) -> None:
        record = SentMessage(mobile=mobile, message=message)
        self.sent.append(record)
        logger.info("[MockSmsSender] SMS to %s: %s", mobile, message)


class LiveSmsSender(SmsSender):
    """Placeholder for the live SMS provider integration.

    The real provider (e.g. an HTTP gateway) is wired here for non-development
    environments. Until implemented, calling :meth:`send` raises
    ``NotImplementedError`` so a misconfigured environment fails loudly rather
    than silently dropping OTP delivery.
    """

    async def send(self, mobile: str, message: str) -> None:
        raise NotImplementedError(
            "LiveSmsSender is not implemented; configure a real SMS provider "
            "for non-development environments."
        )


def get_sms_sender(settings: Settings | None = None) -> SmsSender:
    """Return the SMS sender appropriate for the current environment.

    Returns a :class:`MockSmsSender` when the deployment environment is
    development (Req 2.10); otherwise returns a :class:`LiveSmsSender`.

    Args:
        settings: optional settings override (defaults to the process settings).
    """
    settings = settings or get_settings()
    if settings.is_development:
        return MockSmsSender()
    return LiveSmsSender()

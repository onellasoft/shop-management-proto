"""Smoke unit test for environment-based SMS sender wiring (Task 5.3).

Requirement 2.10: WHERE the deployment environment is development, THE
Auth_Service SHALL use a mock SMS service in place of the live SMS provider.

The ``get_sms_sender`` factory selects the implementation from ``Settings``:
a :class:`MockSmsSender` when the environment is development, and a
:class:`LiveSmsSender` otherwise. These tests assert that resolution directly
against explicit ``Settings`` instances so the wiring is independent of the
ambient process environment.
"""

from __future__ import annotations

from app.core.config import Environment, Settings
from app.services.sms_sender import (
    LiveSmsSender,
    MockSmsSender,
    get_sms_sender,
)


def test_development_environment_resolves_mock_sms_sender():
    """Development resolves the mock SMS sender (Req 2.10)."""
    settings = Settings(environment=Environment.DEVELOPMENT)

    sender = get_sms_sender(settings)

    assert isinstance(sender, MockSmsSender)


def test_production_environment_resolves_live_sms_sender():
    """Non-development (production) resolves the live SMS sender (Req 2.10)."""
    settings = Settings(environment=Environment.PRODUCTION)

    sender = get_sms_sender(settings)

    assert isinstance(sender, LiveSmsSender)
    assert not isinstance(sender, MockSmsSender)


def test_staging_environment_resolves_live_sms_sender():
    """Staging (non-development) resolves the live SMS sender (Req 2.10)."""
    settings = Settings(environment=Environment.STAGING)

    sender = get_sms_sender(settings)

    assert isinstance(sender, LiveSmsSender)

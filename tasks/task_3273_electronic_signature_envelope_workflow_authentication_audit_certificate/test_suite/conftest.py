"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle and API_BASE_URL injection are the runner's job; this file
only wires the generated helpers into pytest.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """Opaque PlatformAdmin identity."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def account_headers() -> dict:
    """Fallback Account identity for calls that are not ownership-gated.

    Ownership-gated calls must use ``make_account_headers(account_id)``.
    """
    return TEST_USERS["account_headers"]


@pytest.fixture
def recipient_headers() -> dict:
    """Fallback Recipient identity for calls that are not ownership-gated.

    Ownership-gated calls must use ``make_recipient_headers(recipient_id)``.
    """
    return TEST_USERS["recipient_headers"]
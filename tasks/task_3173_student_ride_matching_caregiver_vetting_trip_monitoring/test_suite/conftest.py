"""Pytest fixtures exposing the test_helpers infrastructure.

Server lifecycle and ``API_BASE_URL`` injection belong to the runner; nothing
here starts, stops or health-checks the server.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def platform_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def support_headers():
    return TEST_USERS["support_center_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def driver_headers_fallback():
    """Fallback driver headers — never use for an ownership-gated call."""
    return TEST_USERS["driver_headers"]
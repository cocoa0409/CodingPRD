"""Pytest fixtures exposing the generated test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def research_analyst_headers():
    """Fallback only — scope-gated calls must use a real analyst's id."""
    return TEST_USERS["research_analyst_headers"]


@pytest.fixture
def seat_user_headers():
    return TEST_USERS["seat_user_headers"]


@pytest.fixture
def licensing_admin_headers():
    return TEST_USERS["licensing_admin_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def broker_publisher_headers():
    return TEST_USERS["broker_publisher_headers"]
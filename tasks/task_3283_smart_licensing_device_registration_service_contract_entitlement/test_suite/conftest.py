"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def account_admin_headers():
    return TEST_USERS["account_admin_headers"]


@pytest.fixture
def partner_manager_headers():
    return TEST_USERS["partner_manager_headers"]


@pytest.fixture
def logistics_agent_headers():
    return TEST_USERS["logistics_agent_headers"]

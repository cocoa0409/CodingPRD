"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def system_webhook_headers():
    return TEST_USERS["system_webhook_headers"]


@pytest.fixture
def team_owner_headers():
    return TEST_USERS["team_owner_headers"]


@pytest.fixture
def team_billing_manager_headers():
    return TEST_USERS["team_billing_manager_headers"]


@pytest.fixture
def developer_headers():
    return TEST_USERS["developer_headers"]


@pytest.fixture
def viewer_headers():
    return TEST_USERS["viewer_headers"]

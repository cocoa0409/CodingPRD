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
def security_admin_headers():
    return TEST_USERS["security_admin_headers"]


@pytest.fixture
def security_admin_2_headers():
    return TEST_USERS["security_admin_2_headers"]


@pytest.fixture
def procurement_admin_headers():
    return TEST_USERS["procurement_admin_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def helpdesk_agent_headers():
    return TEST_USERS["helpdesk_agent_headers"]


@pytest.fixture
def helpdesk_agent_2_headers():
    return TEST_USERS["helpdesk_agent_2_headers"]

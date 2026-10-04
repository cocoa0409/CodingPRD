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
def league_ops_headers():
    return TEST_USERS["league_ops_headers"]


@pytest.fixture
def support_agent_headers():
    return TEST_USERS["support_agent_headers"]


@pytest.fixture
def support_agent_other_headers():
    return TEST_USERS["support_agent_other_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def venue_manager_headers():
    return TEST_USERS["venue_manager_headers"]

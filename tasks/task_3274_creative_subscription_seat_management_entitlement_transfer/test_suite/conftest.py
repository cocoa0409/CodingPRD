"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def org_admin_headers():
    return TEST_USERS["org_admin_headers"]


@pytest.fixture
def deployment_admin_headers():
    return TEST_USERS["deployment_admin_headers"]


@pytest.fixture
def reseller_agent_headers():
    return TEST_USERS["reseller_agent_headers"]


@pytest.fixture
def end_user_headers():
    return TEST_USERS["end_user_headers"]

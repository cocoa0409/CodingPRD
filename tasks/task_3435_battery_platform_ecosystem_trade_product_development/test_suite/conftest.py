"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the server is
reachable at API_BASE_URL and starts empty for every test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def product_engineer_headers():
    return TEST_USERS["product_engineer_headers"]


@pytest.fixture
def compliance_engineer_headers():
    return TEST_USERS["compliance_engineer_headers"]


@pytest.fixture
def field_researcher_headers():
    return TEST_USERS["field_researcher_headers"]


@pytest.fixture
def service_agent_headers():
    return TEST_USERS["service_agent_headers"]


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def channel_manager_headers():
    return TEST_USERS["channel_manager_headers"]

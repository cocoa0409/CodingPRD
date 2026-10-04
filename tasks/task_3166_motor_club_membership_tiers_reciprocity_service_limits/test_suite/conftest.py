"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def club_admin_headers():
    return TEST_USERS["club_admin_headers"]


@pytest.fixture
def member_services_rep_headers():
    return TEST_USERS["member_services_rep_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def provider_ops_headers():
    return TEST_USERS["provider_ops_headers"]


@pytest.fixture
def settlement_clerk_headers():
    return TEST_USERS["settlement_clerk_headers"]


@pytest.fixture
def federation_finance_headers():
    return TEST_USERS["federation_finance_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]

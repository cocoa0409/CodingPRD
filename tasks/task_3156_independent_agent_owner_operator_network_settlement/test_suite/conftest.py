"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner,
    which restarts the server before every test."""
    return api_client


@pytest.fixture
def freight_agent_headers():
    return TEST_USERS["freight_agent_headers"]


@pytest.fixture
def capacity_owner_headers():
    return TEST_USERS["capacity_owner_headers"]


@pytest.fixture
def safety_reviewer_headers():
    return TEST_USERS["safety_reviewer_headers"]


@pytest.fixture
def settlement_operator_headers():
    return TEST_USERS["settlement_operator_headers"]


@pytest.fixture
def settlement_operator_headers_2():
    return TEST_USERS["settlement_operator_headers_2"]


@pytest.fixture
def network_admin_headers():
    return TEST_USERS["network_admin_headers"]


@pytest.fixture
def agent_manager_headers():
    return TEST_USERS["agent_manager_headers"]
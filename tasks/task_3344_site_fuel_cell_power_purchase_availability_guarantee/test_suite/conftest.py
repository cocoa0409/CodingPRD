"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle (it restarts the API server via start.sh
before every individual test) and injects API_BASE_URL; nothing here starts,
stops or health-checks the server.
"""
import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def site_operator_headers():
    return TEST_USERS["site_operator_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def fuel_coordinator_headers():
    return TEST_USERS["fuel_coordinator_headers"]


@pytest.fixture
def service_engineer_headers():
    return TEST_USERS["service_engineer_headers"]


@pytest.fixture
def settlement_analyst_headers():
    return TEST_USERS["settlement_analyst_headers"]


@pytest.fixture
def settlement_approver_headers():
    return TEST_USERS["settlement_approver_headers"]
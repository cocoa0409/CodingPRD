"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


# One fixture per declared role.
@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]


@pytest.fixture
def ops_manager_headers():
    return TEST_USERS["ops_manager_headers"]


@pytest.fixture
def allocations_coordinator_headers():
    return TEST_USERS["allocations_coordinator_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def financial_ops_headers():
    return TEST_USERS["financial_ops_headers"]


@pytest.fixture
def concierge_desk_staff_headers():
    return TEST_USERS["concierge_desk_staff_headers"]


@pytest.fixture
def producer_analyst_headers():
    return TEST_USERS["producer_analyst_headers"]


@pytest.fixture
def demand_analyst_headers():
    return TEST_USERS["demand_analyst_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def purchasing_manager_headers():
    return TEST_USERS["purchasing_manager_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def inventory_planner_headers():
    return TEST_USERS["inventory_planner_headers"]


@pytest.fixture
def marketing_manager_headers():
    return TEST_USERS["marketing_manager_headers"]


@pytest.fixture
def store_clerk_headers():
    return TEST_USERS["store_clerk_headers"]


@pytest.fixture
def warranty_adjuster_headers():
    return TEST_USERS["warranty_adjuster_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]

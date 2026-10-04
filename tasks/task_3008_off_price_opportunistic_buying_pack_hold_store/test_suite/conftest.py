"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def senior_buyer_headers():
    return TEST_USERS["senior_buyer_headers"]


@pytest.fixture
def junior_buyer_headers():
    return TEST_USERS["junior_buyer_headers"]


@pytest.fixture
def planning_lead_headers():
    return TEST_USERS["planning_lead_headers"]


@pytest.fixture
def allocation_manager_headers():
    return TEST_USERS["allocation_manager_headers"]


@pytest.fixture
def inventory_planner_headers():
    return TEST_USERS["inventory_planner_headers"]


@pytest.fixture
def pricing_analyst_headers():
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def warehouse_clerk_headers():
    return TEST_USERS["warehouse_clerk_headers"]


@pytest.fixture
def store_ops_lead_headers():
    return TEST_USERS["store_ops_lead_headers"]


@pytest.fixture
def shrink_auditor_headers():
    return TEST_USERS["shrink_auditor_headers"]

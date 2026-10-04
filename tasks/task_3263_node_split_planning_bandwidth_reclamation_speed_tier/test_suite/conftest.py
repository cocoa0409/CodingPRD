"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def network_planner_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def capacity_engineer_headers():
    return TEST_USERS["capacity_engineer_headers"]


@pytest.fixture
def field_ops_coordinator_headers():
    return TEST_USERS["field_ops_coordinator_headers"]


@pytest.fixture
def franchise_admin_headers():
    return TEST_USERS["franchise_admin_headers"]


@pytest.fixture
def provisioning_agent_headers():
    return TEST_USERS["provisioning_agent_headers"]


@pytest.fixture
def customer_care_headers():
    return TEST_USERS["customer_care_headers"]

"""Pytest fixtures exposing the rollout test_helpers infrastructure."""

import pytest
from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def real_estate_manager_headers():
    return TEST_USERS["real_estate_manager_headers"]


@pytest.fixture
def network_planner_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def operations_lead_headers():
    return TEST_USERS["operations_lead_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]

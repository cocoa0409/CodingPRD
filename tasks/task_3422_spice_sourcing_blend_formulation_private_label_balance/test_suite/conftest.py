"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def supply_planner_headers():
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def quality_analyst_headers():
    return TEST_USERS["quality_analyst_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def flavor_scientist_headers():
    return TEST_USERS["flavor_scientist_headers"]


@pytest.fixture
def production_scheduler_headers():
    return TEST_USERS["production_scheduler_headers"]


@pytest.fixture
def recall_coordinator_headers():
    return TEST_USERS["recall_coordinator_headers"]

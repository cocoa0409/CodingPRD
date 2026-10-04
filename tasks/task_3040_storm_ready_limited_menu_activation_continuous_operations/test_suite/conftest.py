"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def unit_manager_headers():
    return TEST_USERS["unit_manager_headers"]


@pytest.fixture
def logistics_planner_headers():
    return TEST_USERS["logistics_planner_headers"]


@pytest.fixture
def field_coordinator_headers():
    return TEST_USERS["field_coordinator_headers"]


@pytest.fixture
def relief_coordinator_headers():
    return TEST_USERS["relief_coordinator_headers"]

"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def regional_ops_headers():
    return TEST_USERS["regional_ops_headers"]


@pytest.fixture
def category_manager_headers():
    return TEST_USERS["category_manager_headers"]


@pytest.fixture
def depot_manager_headers():
    return TEST_USERS["depot_manager_headers"]


@pytest.fixture
def depot_planner_headers():
    return TEST_USERS["depot_planner_headers"]


@pytest.fixture
def membership_desk_headers():
    return TEST_USERS["membership_desk_headers"]


@pytest.fixture
def vendor_rep_headers():
    return TEST_USERS["vendor_rep_headers"]

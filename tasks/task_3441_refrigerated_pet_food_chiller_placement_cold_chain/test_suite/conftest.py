"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def placement_manager_headers():
    return TEST_USERS["placement_manager_headers"]


@pytest.fixture
def store_operator_headers():
    return TEST_USERS["store_operator_headers"]


@pytest.fixture
def service_dispatcher_headers():
    return TEST_USERS["service_dispatcher_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]

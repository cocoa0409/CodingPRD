"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def network_planner_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def ops_controller_headers():
    return TEST_USERS["ops_controller_headers"]


@pytest.fixture
def crew_scheduler_headers():
    return TEST_USERS["crew_scheduler_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def finance_analyst_headers():
    return TEST_USERS["finance_analyst_headers"]

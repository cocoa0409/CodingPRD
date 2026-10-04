"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["facility_planner_headers"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["route_dispatcher_headers"]


@pytest.fixture
def donation_headers():
    return TEST_USERS["donation_coordinator_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_admin_headers"]


@pytest.fixture
def cafe_manager_headers():
    return TEST_USERS["cafe_manager_headers"]

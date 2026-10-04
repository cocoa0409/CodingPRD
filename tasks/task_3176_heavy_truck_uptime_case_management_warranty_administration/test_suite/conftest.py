"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def uptime_coordinator_headers():
    return TEST_USERS["uptime_coordinator_headers"]


@pytest.fixture
def dealer_advisor_headers():
    return TEST_USERS["dealer_advisor_headers"]


@pytest.fixture
def parts_manager_headers():
    return TEST_USERS["parts_manager_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def supplier_manager_headers():
    return TEST_USERS["supplier_manager_headers"]

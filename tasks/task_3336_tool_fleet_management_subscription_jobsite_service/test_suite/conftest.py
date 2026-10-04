"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def service_coordinator_headers():
    return TEST_USERS["service_coordinator_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def field_engineer_headers():
    return TEST_USERS["field_engineer_headers"]


@pytest.fixture
def contractor_manager_headers():
    return TEST_USERS["contractor_manager_headers"]


@pytest.fixture
def jobsite_supervisor_headers():
    return TEST_USERS["jobsite_supervisor_headers"]

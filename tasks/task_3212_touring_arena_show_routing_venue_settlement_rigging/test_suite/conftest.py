"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def tour_manager_headers():
    return TEST_USERS["tour_manager_headers"]


@pytest.fixture
def venue_booker_headers():
    return TEST_USERS["venue_booker_headers"]


@pytest.fixture
def production_engineer_headers():
    return TEST_USERS["production_engineer_headers"]


@pytest.fixture
def production_engineer_b_headers():
    return TEST_USERS["production_engineer_b_headers"]


@pytest.fixture
def labor_steward_headers():
    return TEST_USERS["labor_steward_headers"]


@pytest.fixture
def box_office_manager_headers():
    return TEST_USERS["box_office_manager_headers"]


@pytest.fixture
def licensing_manager_headers():
    return TEST_USERS["licensing_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]

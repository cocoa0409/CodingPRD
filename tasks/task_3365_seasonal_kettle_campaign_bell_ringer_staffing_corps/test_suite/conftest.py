"""Pytest fixtures exposing test_helpers infrastructure.

The runner supplies PYTHONPATH and API_BASE_URL; the server is started fresh
before every test, so each test builds its own world from an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def territorial_commander_headers():
    return TEST_USERS["territorial_commander_headers"]


@pytest.fixture
def kettle_coordinator_headers():
    return TEST_USERS["kettle_coordinator_headers"]


@pytest.fixture
def volunteer_coordinator_headers():
    return TEST_USERS["volunteer_coordinator_headers"]


@pytest.fixture
def counting_room_teller_headers():
    return TEST_USERS["counting_room_teller_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def digital_giving_processor_headers():
    return TEST_USERS["digital_giving_processor_headers"]


@pytest.fixture
def assistance_caseworker_headers():
    return TEST_USERS["assistance_caseworker_headers"]


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def disaster_services_coordinator_headers():
    return TEST_USERS["disaster_services_coordinator_headers"]

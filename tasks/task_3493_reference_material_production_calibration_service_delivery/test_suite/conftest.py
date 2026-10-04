"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def metrologist_headers():
    return TEST_USERS["metrologist_headers"]


@pytest.fixture
def certification_officer_headers():
    return TEST_USERS["certification_officer_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def calibration_coordinator_headers():
    return TEST_USERS["calibration_coordinator_headers"]


@pytest.fixture
def accreditation_officer_headers():
    return TEST_USERS["accreditation_officer_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]

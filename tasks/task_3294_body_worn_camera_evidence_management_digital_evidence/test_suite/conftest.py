"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]


@pytest.fixture
def device_coordinator_headers():
    return TEST_USERS["device_coordinator_headers"]


@pytest.fixture
def redaction_technician_headers():
    return TEST_USERS["redaction_technician_headers"]


@pytest.fixture
def records_officer_headers():
    return TEST_USERS["records_officer_headers"]


@pytest.fixture
def prosecutor_headers():
    return TEST_USERS["prosecutor_headers"]


@pytest.fixture
def defense_counsel_headers():
    return TEST_USERS["defense_counsel_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]

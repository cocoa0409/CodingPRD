"""Pytest fixtures exposing the test_helpers infrastructure.

The runner supplies API_BASE_URL and restarts the server before every test, so
each test starts against an empty database.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def property_manager_headers():
    return TEST_USERS["property_manager_headers"]


@pytest.fixture
def hardware_technician_headers():
    return TEST_USERS["hardware_technician_headers"]


@pytest.fixture
def maintenance_technician_headers():
    return TEST_USERS["maintenance_technician_headers"]


@pytest.fixture
def leasing_agent_headers():
    return TEST_USERS["leasing_agent_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]
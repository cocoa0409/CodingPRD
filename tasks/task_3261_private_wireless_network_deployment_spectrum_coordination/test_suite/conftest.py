"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def network_architect_headers():
    return TEST_USERS["network_architect_headers"]


@pytest.fixture
def rf_engineer_headers():
    return TEST_USERS["rf_engineer_headers"]


@pytest.fixture
def spectrum_coordinator_headers():
    return TEST_USERS["spectrum_coordinator_headers"]


@pytest.fixture
def spectrum_regulator_headers():
    return TEST_USERS["spectrum_regulator_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]

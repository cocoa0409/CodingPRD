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
def flow_controller_headers():
    return TEST_USERS["flow_controller_headers"]


@pytest.fixture
def station_operator_headers():
    return TEST_USERS["station_operator_headers"]


@pytest.fixture
def floor_supervisor_headers():
    return TEST_USERS["floor_supervisor_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def safety_officer_2_headers():
    return TEST_USERS["safety_officer_2_headers"]


@pytest.fixture
def maintenance_tech_headers():
    return TEST_USERS["maintenance_tech_headers"]


@pytest.fixture
def release_engineer_headers():
    return TEST_USERS["release_engineer_headers"]

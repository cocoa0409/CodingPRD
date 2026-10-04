"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def incident_commander_headers():
    return TEST_USERS["incident_commander_headers"]


@pytest.fixture
def operations_lead_headers():
    return TEST_USERS["operations_lead_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def partner_liaison_headers():
    return TEST_USERS["partner_liaison_headers"]


@pytest.fixture
def training_director_headers():
    return TEST_USERS["training_director_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]

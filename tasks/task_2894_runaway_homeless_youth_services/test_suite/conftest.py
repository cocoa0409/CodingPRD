"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def outreach_worker_headers():
    return TEST_USERS["outreach_worker_headers"]


@pytest.fixture
def outreach_worker_alt_headers():
    return TEST_USERS["outreach_worker_alt_headers"]


@pytest.fixture
def shelter_case_manager_headers():
    return TEST_USERS["shelter_case_manager_headers"]


@pytest.fixture
def shelter_case_manager_alt_headers():
    return TEST_USERS["shelter_case_manager_alt_headers"]


@pytest.fixture
def reunification_specialist_headers():
    return TEST_USERS["reunification_specialist_headers"]


@pytest.fixture
def reunification_specialist_alt_headers():
    return TEST_USERS["reunification_specialist_alt_headers"]


@pytest.fixture
def tlp_coordinator_headers():
    return TEST_USERS["tlp_coordinator_headers"]


@pytest.fixture
def tlp_coordinator_alt_headers():
    return TEST_USERS["tlp_coordinator_alt_headers"]


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def program_admin_alt_headers():
    return TEST_USERS["program_admin_alt_headers"]

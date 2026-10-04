"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle, API_BASE_URL injection, and PYTHONPATH; the
tests assume the server is already running and reachable (PRD §4 routes).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def duty_officer_headers():
    return TEST_USERS["duty_officer_headers"]


@pytest.fixture
def managing_director_headers():
    return TEST_USERS["managing_director_headers"]


@pytest.fixture
def md_proposer_headers():
    return TEST_USERS["md_proposer_headers"]


@pytest.fixture
def md_adopter_headers():
    return TEST_USERS["md_adopter_headers"]


@pytest.fixture
def iic_headers():
    return TEST_USERS["iic_headers"]


@pytest.fixture
def group_chairman_headers():
    return TEST_USERS["group_chairman_headers"]


@pytest.fixture
def party_coordinator_headers():
    return TEST_USERS["party_coordinator_headers"]


@pytest.fixture
def addressee_contact_headers():
    return TEST_USERS["addressee_contact_headers"]


@pytest.fixture
def recorder_custodian_headers():
    return TEST_USERS["recorder_custodian_headers"]


@pytest.fixture
def docket_officer_headers():
    return TEST_USERS["docket_officer_headers"]


@pytest.fixture
def board_admin_headers():
    return TEST_USERS["board_admin_headers"]


@pytest.fixture
def board_member_headers():
    return TEST_USERS["board_member_headers"]

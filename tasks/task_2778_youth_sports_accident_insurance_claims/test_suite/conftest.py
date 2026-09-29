"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_administrator_headers"]


@pytest.fixture
def league_official_headers():
    return TEST_USERS["league_official_headers"]


@pytest.fixture
def verifying_official_headers():
    return TEST_USERS["verifying_official_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def medical_reviewer_headers():
    return TEST_USERS["medical_reviewer_headers"]


@pytest.fixture
def league_administrator_headers():
    return TEST_USERS["league_administrator_headers"]


@pytest.fixture
def guardian_portal_headers():
    return TEST_USERS["guardian_portal_headers"]

"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def care_coordinator_headers():
    return TEST_USERS["care_coordinator_headers"]


@pytest.fixture
def physician_reviewer_headers():
    return TEST_USERS["physician_reviewer_headers"]


@pytest.fixture
def claims_admin_headers():
    return TEST_USERS["claims_admin_headers"]


@pytest.fixture
def employer_rep_headers():
    return TEST_USERS["employer_rep_headers"]

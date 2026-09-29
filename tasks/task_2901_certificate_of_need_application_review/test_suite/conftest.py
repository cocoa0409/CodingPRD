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
def intake_analyst_headers():
    return TEST_USERS["intake_analyst_headers"]


@pytest.fixture
def intake_analyst_2_headers():
    return TEST_USERS["intake_analyst_2_headers"]


@pytest.fixture
def review_analyst_headers():
    return TEST_USERS["review_analyst_headers"]


@pytest.fixture
def review_analyst_2_headers():
    return TEST_USERS["review_analyst_2_headers"]


@pytest.fixture
def review_analyst_3_headers():
    return TEST_USERS["review_analyst_3_headers"]


@pytest.fixture
def decision_officer_headers():
    return TEST_USERS["decision_officer_headers"]


@pytest.fixture
def appeal_board_headers():
    return TEST_USERS["appeal_board_headers"]


@pytest.fixture
def public_participant_headers():
    return TEST_USERS["public_participant_headers"]


@pytest.fixture
def applicant_headers():
    """Fallback Applicant headers for calls that never reach an ownership check."""
    return TEST_USERS["applicant_headers"]

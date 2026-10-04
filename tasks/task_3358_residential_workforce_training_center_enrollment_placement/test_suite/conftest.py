"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def counselor_headers():
    return TEST_USERS["admissions_counselor_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["eligibility_reviewer_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["enrollment_manager_headers"]


@pytest.fixture
def advisor_headers():
    return TEST_USERS["residential_advisor_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["career_instructor_headers"]


@pytest.fixture
def specialist_headers():
    return TEST_USERS["transition_specialist_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["operator_admin_headers"]

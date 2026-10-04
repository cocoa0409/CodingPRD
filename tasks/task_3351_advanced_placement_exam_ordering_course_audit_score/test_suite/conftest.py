"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def platform_admin_2_headers():
    return TEST_USERS["platform_admin_2_headers"]


@pytest.fixture
def course_audit_reviewer_headers():
    return TEST_USERS["course_audit_reviewer_headers"]


@pytest.fixture
def course_audit_reviewer_2_headers():
    return TEST_USERS["course_audit_reviewer_2_headers"]


@pytest.fixture
def accommodation_reviewer_headers():
    return TEST_USERS["accommodation_reviewer_headers"]


@pytest.fixture
def accommodation_reviewer_2_headers():
    return TEST_USERS["accommodation_reviewer_2_headers"]


@pytest.fixture
def scoring_specialist_headers():
    return TEST_USERS["scoring_specialist_headers"]


@pytest.fixture
def scoring_specialist_2_headers():
    return TEST_USERS["scoring_specialist_2_headers"]


@pytest.fixture
def integrity_investigator_headers():
    return TEST_USERS["integrity_investigator_headers"]


@pytest.fixture
def integrity_investigator_2_headers():
    return TEST_USERS["integrity_investigator_2_headers"]


@pytest.fixture
def unbound_school_coordinator_headers():
    """Fallback identity only: never use for an ownership-gated call."""
    return TEST_USERS["school_coordinator_headers"]

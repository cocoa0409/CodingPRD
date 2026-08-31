"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_applicant_headers,
    make_compliance_auditor_headers,
    make_recruiter_headers,
    make_safety_director_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def recruiter_headers():
    return TEST_USERS["recruiter_headers"]


@pytest.fixture
def der_headers():
    return TEST_USERS["der_headers"]


@pytest.fixture
def safety_director_headers():
    return TEST_USERS["safety_director_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def school_coordinator_headers():
    return TEST_USERS["school_coordinator_headers"]


@pytest.fixture
def applicant_headers_for():
    """Builder for the entity-backed Applicant role: pass the applicant's id."""
    return make_applicant_headers


@pytest.fixture
def recruiter_headers_for():
    return make_recruiter_headers


@pytest.fixture
def safety_director_headers_for():
    return make_safety_director_headers


@pytest.fixture
def compliance_auditor_headers_for():
    return make_compliance_auditor_headers

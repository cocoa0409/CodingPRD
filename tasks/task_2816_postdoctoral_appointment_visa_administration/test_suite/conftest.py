"""Pytest fixtures exposing the shared test infrastructure."""

import pytest
from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_faculty_mentor_headers,
    make_postdoc_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_alt_headers():
    return TEST_USERS["officer_alt_headers"]


@pytest.fixture
def hr_approver_headers():
    return TEST_USERS["hr_approver_headers"]


@pytest.fixture
def hr_approver_alt_headers():
    return TEST_USERS["hr_approver_alt_headers"]


@pytest.fixture
def export_reviewer_headers():
    return TEST_USERS["export_reviewer_headers"]


@pytest.fixture
def export_reviewer_alt_headers():
    return TEST_USERS["export_reviewer_alt_headers"]


@pytest.fixture
def scholar_advisor_headers():
    return TEST_USERS["scholar_advisor_headers"]


@pytest.fixture
def faculty_mentor_headers():
    return TEST_USERS["faculty_mentor_headers"]


@pytest.fixture
def postdoc_headers():
    return TEST_USERS["postdoc_headers"]


@pytest.fixture
def mentor_headers_for():
    """Builder threading a real mentor record id into `X-User-ID`."""
    return make_faculty_mentor_headers


@pytest.fixture
def postdoc_headers_for():
    """Builder threading a real scholar record id into `X-User-ID`."""
    return make_postdoc_headers

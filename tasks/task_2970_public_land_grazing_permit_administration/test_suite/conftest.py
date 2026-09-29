"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def officer_headers():
    """AuthorizedOfficer — opaque operator identifier u_officer_1 (PRD 2.1)."""
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_2_headers():
    """A second AuthorizedOfficer identity, for segregation-of-duties tests."""
    return TEST_USERS["officer_2_headers"]


@pytest.fixture
def specialist_headers():
    """RangeSpecialist — opaque operator identifier u_spec_1 (PRD 2.1)."""
    return TEST_USERS["specialist_headers"]


@pytest.fixture
def specialist_2_headers():
    return TEST_USERS["specialist_2_headers"]


@pytest.fixture
def adjudicator_headers():
    """AppealsAdjudicator — opaque operator identifier u_judge_1 (PRD 2.1)."""
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def adjudicator_2_headers():
    return TEST_USERS["adjudicator_2_headers"]


@pytest.fixture
def system_admin_headers():
    """SystemAdmin — may call only the clock endpoint (PRD 4)."""
    return TEST_USERS["system_admin_headers"]

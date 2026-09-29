"""Shared pytest fixtures.

The harness restarts the server before every individual test, so each test
begins against an empty database and builds every precondition it needs from
scratch through the endpoints the PRD declares.
"""
import pytest

from test_helpers import TEST_USERS, api_client


@pytest.fixture(scope="session")
def api():
    """The API client every test drives the service through."""
    return api_client


@pytest.fixture
def analyst_headers():
    """`RatingAnalyst` analyst-1, the analyst assigned to the canonical cycle."""
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def other_analyst_headers():
    """A second `RatingAnalyst` who owns none of the cycles under test."""
    return TEST_USERS["other_analyst_headers"]


@pytest.fixture
def reviewer_headers():
    """`PublishingReviewer` reviewer-1, who never scores a cycle."""
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def other_reviewer_headers():
    return TEST_USERS["other_reviewer_headers"]


@pytest.fixture
def admin_headers():
    """`MethodologyAdmin` admin-1, the standards administrator."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def other_admin_headers():
    return TEST_USERS["other_admin_headers"]


@pytest.fixture
def panelist_headers():
    """The first seated `AppealPanelist`."""
    return TEST_USERS["panelist_headers"]


@pytest.fixture
def public_headers():
    """A `PublicUser` donor reading published ratings and filing complaints."""
    return TEST_USERS["public_headers"]


@pytest.fixture
def org_rep_headers():
    """An `OrganizationRep` whose `X-User-ID` is not any real organization id."""
    return TEST_USERS["org_rep_headers"]

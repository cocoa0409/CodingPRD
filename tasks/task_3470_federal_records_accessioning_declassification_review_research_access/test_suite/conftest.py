"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns server lifecycle and injects API_BASE_URL; tests only consume
the session-scoped client and the per-role header constants.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def appraiser_2_headers():
    return TEST_USERS["appraiser_2_headers"]


@pytest.fixture
def processing_archivist_headers():
    return TEST_USERS["processing_archivist_headers"]


@pytest.fixture
def declass_reviewer_headers():
    return TEST_USERS["declass_reviewer_headers"]


@pytest.fixture
def chief_archivist_headers():
    return TEST_USERS["chief_archivist_headers"]


@pytest.fixture
def research_room_staff_headers():
    return TEST_USERS["research_room_staff_headers"]


@pytest.fixture
def foia_officer_headers():
    return TEST_USERS["foia_officer_headers"]


@pytest.fixture
def foia_officer_2_headers():
    return TEST_USERS["foia_officer_2_headers"]


@pytest.fixture
def foia_appeals_officer_headers():
    return TEST_USERS["foia_appeals_officer_headers"]

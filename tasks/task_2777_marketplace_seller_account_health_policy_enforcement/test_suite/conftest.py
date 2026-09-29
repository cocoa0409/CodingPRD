"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle, API_BASE_URL and PYTHONPATH; tests never
start, stop or health-check the server. The server is relaunched before every
individual test, so each test begins against an empty database and builds the
state it needs through the PRD's own endpoints.
"""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def investigator_alt_headers():
    return TEST_USERS["investigator_alt_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["appeal_reviewer_headers"]


@pytest.fixture
def reviewer_alt_headers():
    return TEST_USERS["appeal_reviewer_alt_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def officer_alt_headers():
    return TEST_USERS["compliance_officer_alt_headers"]


@pytest.fixture
def anonymous_headers():
    """PRD §2.1: the Anonymous role is the only one that may omit X-User-ID."""
    return TEST_USERS["anonymous_headers"]

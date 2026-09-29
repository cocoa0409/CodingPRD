"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns the server lifecycle, API_BASE_URL and PYTHONPATH; tests never
start, stop or health-check the server. The server is relaunched before every
individual test, so each test begins against an empty database.
"""

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
def program_admin_alt_headers():
    return TEST_USERS["program_admin_alt_headers"]


@pytest.fixture
def credentialing_officer_headers():
    return TEST_USERS["credentialing_officer_headers"]


@pytest.fixture
def scheduling_coordinator_headers():
    return TEST_USERS["scheduling_coordinator_headers"]


@pytest.fixture
def fiscal_officer_headers():
    return TEST_USERS["fiscal_officer_headers"]


@pytest.fixture
def fiscal_officer_alt_headers():
    return TEST_USERS["fiscal_officer_alt_headers"]


@pytest.fixture
def quality_reviewer_headers():
    return TEST_USERS["quality_reviewer_headers"]


@pytest.fixture
def quality_reviewer_alt_headers():
    return TEST_USERS["quality_reviewer_alt_headers"]


@pytest.fixture
def quality_reviewer_third_headers():
    return TEST_USERS["quality_reviewer_third_headers"]


@pytest.fixture
def interpreter_headers():
    """Shared fallback only — ownership-gated calls must use
    make_interpreter_headers(interpreter["id"])."""
    return TEST_USERS["interpreter_headers"]

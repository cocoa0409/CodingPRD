"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed by prd-bench-local-runner; tests assume the
API is reachable at API_BASE_URL and that the database is empty at the start
of every test (the runner restarts the server before each test).
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (the same singleton test_helpers fixtures use)."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def registry_admin_headers():
    return TEST_USERS["registry_admin_headers"]


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def state_official_headers():
    return TEST_USERS["state_official_headers"]


@pytest.fixture
def exam_proctor_headers():
    return TEST_USERS["exam_proctor_headers"]


@pytest.fixture
def hearing_officer_headers():
    return TEST_USERS["hearing_officer_headers"]


@pytest.fixture
def candidate_headers():
    """Shared fallback Candidate identity — NOT valid for ownership-gated calls."""
    return TEST_USERS["candidate_headers"]

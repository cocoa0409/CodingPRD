"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def candidate_headers():
    """Unbound Candidate headers — safe only for non-ownership-gated calls
    (e.g. self-registration via POST /marketplace/nurses)."""
    return TEST_USERS["candidate_headers"]


@pytest.fixture
def employer_headers():
    """Unbound Employer headers — safe only for non-ownership-gated calls."""
    return TEST_USERS["employer_headers"]

"""Pytest fixtures exposing the test infrastructure to the suite.

Server lifecycle (start/stop/restart per test) and PYTHONPATH are owned by the
benchmark runner; this file only wires up the API client and role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The runner restarts the server per test."""
    return api_client


@pytest.fixture
def admin_headers():
    """Opaque PlatformAdmin identity."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def trust_headers():
    """Opaque TrustReviewer identity."""
    return TEST_USERS["trust_headers"]


@pytest.fixture
def employer_headers():
    """Placeholder Employer identity — use make_employer_headers(id) when the
    call is ownership-gated."""
    return TEST_USERS["employer_headers"]


@pytest.fixture
def seeker_headers():
    """Placeholder JobSeeker identity — use make_seeker_headers(id) when the
    call is ownership-gated."""
    return TEST_USERS["seeker_headers"]
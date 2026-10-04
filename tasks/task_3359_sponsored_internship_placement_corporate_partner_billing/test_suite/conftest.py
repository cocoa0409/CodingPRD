"""Pytest fixtures exposing the test_helpers infrastructure.

The server is already running and reachable at ``API_BASE_URL``; its lifecycle
is owned by the runner, not by these tests.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def staff_headers() -> dict:
    return TEST_USERS["program_staff_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def partner_headers() -> dict:
    return TEST_USERS["partner_headers"]


@pytest.fixture
def student_headers() -> dict:
    return TEST_USERS["student_headers"]

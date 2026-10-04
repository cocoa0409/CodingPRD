"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def requester_headers():
    """Shared Requester headers — safe for calls that are not ownership-gated."""
    return TEST_USERS["requester_headers"]


@pytest.fixture
def worker_headers():
    """Shared Worker headers — safe for calls that are not ownership-gated."""
    return TEST_USERS["worker_headers"]


@pytest.fixture
def no_auth_headers():
    """Headers with neither X-User-ID nor X-User-Role."""
    return {"Content-Type": "application/json"}
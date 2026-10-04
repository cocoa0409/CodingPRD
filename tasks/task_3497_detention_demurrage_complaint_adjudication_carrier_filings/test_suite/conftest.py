"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and injects API_BASE_URL; tests assume the
server is already reachable and freshly restarted (empty database) for every
test function.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def docket_headers():
    return TEST_USERS["docket_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def alj_headers():
    return TEST_USERS["alj_headers"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["counsel_headers"]

"""Pytest fixtures exposing the test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is
reachable at API_BASE_URL and that the database starts empty for each
test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle owned by the runner)."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_1_headers():
    return TEST_USERS["manager_1_headers"]


@pytest.fixture
def manager_2_headers():
    return TEST_USERS["manager_2_headers"]


@pytest.fixture
def manager_3_headers():
    return TEST_USERS["manager_3_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]

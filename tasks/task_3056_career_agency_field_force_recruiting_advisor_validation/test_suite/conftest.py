"""Pytest fixtures exposing the test infrastructure.

Server lifecycle is owned by the runner: it restarts the API server before every
test, so each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def md_headers():
    return TEST_USERS["managing_director_headers"]


@pytest.fixture
def dd_headers():
    return TEST_USERS["district_director_headers"]


@pytest.fixture
def rep_headers():
    return TEST_USERS["financial_rep_headers"]


@pytest.fixture
def ro_headers():
    return TEST_USERS["recruiting_officer_headers"]


@pytest.fixture
def lc_headers():
    return TEST_USERS["licensing_coordinator_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
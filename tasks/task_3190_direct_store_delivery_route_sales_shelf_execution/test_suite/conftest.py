"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and injects API_BASE_URL; the server is
restarted before every test, so each test starts against an empty database.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_admin_headers,
    make_rep_headers,
    make_store_manager_headers,
    make_supervisor_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def supervisor2_headers():
    return TEST_USERS["supervisor2_headers"]


@pytest.fixture
def rep_headers():
    return TEST_USERS["rep_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]

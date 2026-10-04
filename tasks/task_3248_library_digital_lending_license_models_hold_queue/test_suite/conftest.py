"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def consortium_admin_headers():
    return TEST_USERS["consortium_admin_headers"]


@pytest.fixture
def system_analyst_headers():
    return TEST_USERS["system_analyst_headers"]


@pytest.fixture
def library_admin_headers():
    return TEST_USERS["library_admin_headers"]


@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]

"""Pytest fixtures exposing the percentage-rent test helpers."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def center_admin_headers():
    return TEST_USERS["center_admin_headers"]


@pytest.fixture
def lease_administrator_headers():
    return TEST_USERS["lease_administrator_headers"]


@pytest.fixture
def tenant_user_headers():
    return TEST_USERS["tenant_user_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def ownership_analyst_headers():
    return TEST_USERS["ownership_analyst_headers"]

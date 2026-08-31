"""Pytest fixtures exposing the generated test infrastructure."""
import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle belongs to the runner."""
    return api_client


@pytest.fixture
def ops_admin_headers():
    return TEST_USERS["ops_admin_headers"]


@pytest.fixture
def revenue_manager_headers():
    return TEST_USERS["revenue_manager_headers"]


@pytest.fixture
def second_revenue_manager_headers():
    return TEST_USERS["second_revenue_manager_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]


@pytest.fixture
def anonymous_headers():
    return NO_AUTH_HEADERS

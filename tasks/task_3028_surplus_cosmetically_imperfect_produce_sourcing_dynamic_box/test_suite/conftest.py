"""Pytest fixtures exposing the test infrastructure to the suite."""
import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import (
    TEST_USERS,
    make_customer_headers,
    make_operator_headers,
    make_supplier_headers,
    unauth_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's guarantee."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def supplier_headers():
    return TEST_USERS["supplier_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def no_role_headers():
    return unauth_headers()
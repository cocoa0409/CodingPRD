"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def brand_owner_admin_headers():
    return TEST_USERS["brand_owner_admin_headers"]


@pytest.fixture
def bottler_ops_headers():
    return TEST_USERS["bottler_ops_headers"]


@pytest.fixture
def customer_manager_headers():
    return TEST_USERS["customer_manager_headers"]


@pytest.fixture
def field_technician_headers():
    return TEST_USERS["field_technician_headers"]

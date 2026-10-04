"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def store_ops_headers():
    return TEST_USERS["store_ops_headers"]


@pytest.fixture
def delivery_coordinator_headers():
    return TEST_USERS["delivery_coordinator_headers"]


@pytest.fixture
def assembly_provider_headers():
    return TEST_USERS["assembly_provider_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]

"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def distributor_admin_headers():
    return TEST_USERS["distributor_admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def customer_buyer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["customer_buyer_headers"]


@pytest.fixture
def warehouse_ops_headers():
    return TEST_USERS["warehouse_ops_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def supplier_admin_headers():
    return TEST_USERS["supplier_admin_headers"]

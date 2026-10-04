"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import ApiClient, api_client, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def franchise_owner_headers():
    return TEST_USERS["franchise_owner_headers"]


@pytest.fixture
def franchise_manager_headers():
    return TEST_USERS["franchise_manager_headers"]


@pytest.fixture
def credit_officer_headers():
    return TEST_USERS["credit_officer_headers"]


@pytest.fixture
def route_sales_rep_headers():
    return TEST_USERS["route_sales_rep_headers"]


@pytest.fixture
def warranty_admin_headers():
    return TEST_USERS["warranty_admin_headers"]


@pytest.fixture
def technician_headers():
    return TEST_USERS["technician_headers"]

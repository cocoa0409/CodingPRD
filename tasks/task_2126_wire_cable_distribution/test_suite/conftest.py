"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_branch_ops_headers,
    make_credit_manager_headers,
    make_customer_headers,
    make_driver_headers,
    make_platform_admin_headers,
    make_sales_rep_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def sales_rep_2_headers():
    return TEST_USERS["sales_rep_2_headers"]


@pytest.fixture
def credit_manager_headers():
    return TEST_USERS["credit_manager_headers"]


@pytest.fixture
def branch_ops_headers():
    """Unowned BranchOps identity — for tests that never reach an ownership
    check (malformed payloads, unknown identifiers)."""
    return TEST_USERS["branch_ops_headers"]


@pytest.fixture
def driver_headers():
    """Unowned Driver identity — for tests that never reach an ownership check."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def customer_headers():
    """Unowned Customer identity — for tests that never reach an ownership check."""
    return TEST_USERS["customer_headers"]


@pytest.fixture
def branch_ops():
    """Builder binding a BranchOps identity to a real Branch id."""
    return make_branch_ops_headers


@pytest.fixture
def driver():
    """Builder binding a Driver identity to a real Truck id."""
    return make_driver_headers


@pytest.fixture
def customer_role():
    """Builder binding a Customer identity to a real Customer id."""
    return make_customer_headers


@pytest.fixture
def sales_rep():
    """Builder for a SalesRep identity under an arbitrary operator id."""
    return make_sales_rep_headers


@pytest.fixture
def platform_admin():
    """Builder for a PlatformAdmin identity under an arbitrary operator id."""
    return make_platform_admin_headers


@pytest.fixture
def credit_manager():
    """Builder for a CreditManager identity under an arbitrary operator id."""
    return make_credit_manager_headers

"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart per test) is owned by prd-bench-local-runner;
this module only wires the generated helpers into pytest fixtures.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointing at API_BASE_URL."""
    return api_client


@pytest.fixture
def merchandiser_headers():
    return TEST_USERS["merchandiser_headers"]


@pytest.fixture
def inventory_planner_headers():
    return TEST_USERS["inventory_planner_headers"]


@pytest.fixture
def cross_dock_headers():
    return TEST_USERS["cross_dock_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]


@pytest.fixture
def vendor_headers():
    """Fallback Vendor identity for requests that are not ownership-gated."""
    return TEST_USERS["vendor_headers"]


@pytest.fixture
def customer_headers():
    """Fallback Customer identity for requests that are not ownership-gated."""
    return TEST_USERS["customer_headers"]
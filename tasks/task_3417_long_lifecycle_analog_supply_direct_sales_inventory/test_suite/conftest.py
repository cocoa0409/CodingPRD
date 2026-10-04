"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable
at API_BASE_URL and starts each test against an empty database.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client, make_customer_headers


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def supply_planner_headers():
    return TEST_USERS["supply_planner_headers"]


@pytest.fixture
def channel_manager_headers():
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def field_engineer_headers():
    return TEST_USERS["field_engineer_headers"]


@pytest.fixture
def customer_headers_factory():
    """Builder: make_customer_headers(customer_id) for the entity-backed Customer role."""
    return make_customer_headers

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
def zone_admin_headers():
    return TEST_USERS["zone_admin_headers"]


@pytest.fixture
def trust_safety_headers():
    return TEST_USERS["trust_safety_headers"]


@pytest.fixture
def network_planner_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]

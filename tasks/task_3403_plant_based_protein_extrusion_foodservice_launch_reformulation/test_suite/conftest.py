"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests import everything
from test_helpers and assume the API is reachable at API_BASE_URL.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def procurement_manager_headers():
    return TEST_USERS["procurement_manager_headers"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def product_manager_headers():
    return TEST_USERS["product_manager_headers"]


@pytest.fixture
def channel_manager_headers():
    return TEST_USERS["channel_manager_headers"]


@pytest.fixture
def demand_planner_headers():
    return TEST_USERS["demand_planner_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]

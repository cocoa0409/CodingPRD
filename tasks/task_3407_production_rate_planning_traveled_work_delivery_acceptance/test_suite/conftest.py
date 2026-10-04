"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def line_manager_headers():
    return TEST_USERS["line_manager_headers"]


@pytest.fixture
def delivery_manager_headers():
    return TEST_USERS["delivery_manager_headers"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector_headers"]

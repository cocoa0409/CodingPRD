"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the harness; these fixtures assume the server
is already running and reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def distillery_planner_headers() -> dict:
    return TEST_USERS["distillery_planner_headers"]


@pytest.fixture
def operations_director_headers() -> dict:
    return TEST_USERS["operations_director_headers"]


@pytest.fixture
def warehouse_manager_headers() -> dict:
    return TEST_USERS["warehouse_manager_headers"]


@pytest.fixture
def master_blender_headers() -> dict:
    return TEST_USERS["master_blender_headers"]


@pytest.fixture
def program_director_headers() -> dict:
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def bonded_preparer_headers() -> dict:
    return TEST_USERS["bonded_preparer_headers"]


@pytest.fixture
def compliance_officer_headers() -> dict:
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def platform_admin_headers() -> dict:
    return TEST_USERS["platform_admin_headers"]

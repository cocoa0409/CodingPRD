"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def area_director_headers():
    return TEST_USERS["area_director_headers"]


@pytest.fixture
def partnership_manager_headers():
    return TEST_USERS["partnership_manager_headers"]


@pytest.fixture
def program_coordinator_headers():
    return TEST_USERS["program_coordinator_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def funder_headers():
    return TEST_USERS["funder_headers"]

"""Pytest fixtures exposing the service-floor test infrastructure.

The runner owns server lifecycle, PYTHONPATH and API_BASE_URL; these fixtures only
hand the generated ApiClient and role headers to the tests.
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
def floor_manager_headers():
    return TEST_USERS["floor_manager_headers"]


@pytest.fixture
def host_headers():
    return TEST_USERS["host_headers"]


@pytest.fixture
def chef_headers():
    return TEST_USERS["chef_headers"]


@pytest.fixture
def sushi_chef_headers():
    return TEST_USERS["sushi_chef_headers"]
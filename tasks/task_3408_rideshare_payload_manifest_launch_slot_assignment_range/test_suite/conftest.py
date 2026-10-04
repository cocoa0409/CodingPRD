"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the local runner; tests assume the API is
already reachable at API_BASE_URL and that the database is empty per test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def mission_ops_headers():
    return TEST_USERS["mission_ops_headers"]


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def engineer_headers():
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def safety_headers():
    return TEST_USERS["safety_headers"]


@pytest.fixture
def range_officer_headers():
    return TEST_USERS["range_officer_headers"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]

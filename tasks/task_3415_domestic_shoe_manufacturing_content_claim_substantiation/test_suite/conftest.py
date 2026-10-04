"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and API_BASE_URL injection; these fixtures
only bridge the shared API client and role headers into test scope.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin"]


@pytest.fixture
def sourcing_headers():
    return TEST_USERS["sourcing"]


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance"]


@pytest.fixture
def training_headers():
    return TEST_USERS["training"]


@pytest.fixture
def factory_manager_headers():
    return TEST_USERS["factory_manager"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer"]

"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_ops_headers():
    return TEST_USERS["platform_ops_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def aquatics_manager_headers():
    return TEST_USERS["aquatics_manager_headers"]


@pytest.fixture
def gate_attendant_headers():
    return TEST_USERS["gate_attendant_headers"]


@pytest.fixture
def group_headers():
    return TEST_USERS["group_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]
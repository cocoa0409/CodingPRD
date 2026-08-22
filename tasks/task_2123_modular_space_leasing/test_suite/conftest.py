"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def fleet_admin_headers():
    return TEST_USERS["fleet_admin_headers"]


@pytest.fixture
def second_fleet_admin_headers():
    return TEST_USERS["second_fleet_admin_headers"]


@pytest.fixture
def leasing_agent_headers():
    return TEST_USERS["leasing_agent_headers"]


@pytest.fixture
def damage_assessor_headers():
    return TEST_USERS["damage_assessor_headers"]


@pytest.fixture
def branch_ops_headers():
    return TEST_USERS["branch_ops_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]

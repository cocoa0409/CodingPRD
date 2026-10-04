"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def account_executive_headers():
    return TEST_USERS["account_executive_headers"]


@pytest.fixture
def approval_authority_headers():
    return TEST_USERS["approval_authority_headers"]


@pytest.fixture
def transaction_manager_headers():
    return TEST_USERS["transaction_manager_headers"]


@pytest.fixture
def facilities_manager_headers():
    return TEST_USERS["facilities_manager_headers"]


@pytest.fixture
def occupancy_planner_headers():
    return TEST_USERS["occupancy_planner_headers"]


@pytest.fixture
def governance_manager_headers():
    return TEST_USERS["governance_manager_headers"]


@pytest.fixture
def data_steward_headers():
    return TEST_USERS["data_steward_headers"]


@pytest.fixture
def transition_manager_headers():
    return TEST_USERS["transition_manager_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
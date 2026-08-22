"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["show_operations_headers"]


@pytest.fixture
def ops_alt_headers():
    return TEST_USERS["show_operations_alt_headers"]


@pytest.fixture
def labor_headers():
    return TEST_USERS["labor_supervisor_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def adjuster_alt_headers():
    return TEST_USERS["claims_adjuster_alt_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def finance_alt_headers():
    return TEST_USERS["finance_controller_alt_headers"]


@pytest.fixture
def exhibitor_headers():
    return TEST_USERS["exhibitor_headers"]


@pytest.fixture
def warehouse_agent_headers():
    return TEST_USERS["warehouse_agent_headers"]

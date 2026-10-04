"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def contract_manager_headers():
    return TEST_USERS["contract_manager_headers"]


@pytest.fixture
def terminal_operator_headers():
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def equipment_controller_headers():
    return TEST_USERS["equipment_controller_headers"]


@pytest.fixture
def billing_agent_headers():
    return TEST_USERS["billing_agent_headers"]


@pytest.fixture
def credit_supervisor_headers():
    return TEST_USERS["credit_supervisor_headers"]


@pytest.fixture
def credit_director_headers():
    return TEST_USERS["credit_director_headers"]


@pytest.fixture
def customer_rep_headers():
    return TEST_USERS["customer_rep_headers"]

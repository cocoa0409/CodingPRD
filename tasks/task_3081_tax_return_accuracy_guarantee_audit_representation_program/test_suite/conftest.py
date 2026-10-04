"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def office_manager_headers():
    return TEST_USERS["office_manager_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def case_manager_scoper_headers():
    return TEST_USERS["case_manager_scoper_headers"]


@pytest.fixture
def case_manager_resolver_headers():
    return TEST_USERS["case_manager_resolver_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def preparer_headers():
    return TEST_USERS["preparer_headers"]


@pytest.fixture
def enrolled_agent_headers():
    return TEST_USERS["enrolled_agent_headers"]

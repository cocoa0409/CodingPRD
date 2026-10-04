"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def developer_admin_headers():
    return TEST_USERS["developer_admin_headers"]


@pytest.fixture
def origination_manager_headers():
    return TEST_USERS["origination_manager_headers"]


@pytest.fixture
def procurement_lead_headers():
    return TEST_USERS["procurement_lead_headers"]


@pytest.fixture
def construction_manager_headers():
    return TEST_USERS["construction_manager_headers"]


@pytest.fixture
def tax_counsel_headers():
    return TEST_USERS["tax_counsel_headers"]


@pytest.fixture
def investor_manager_headers():
    return TEST_USERS["investor_manager_headers"]


@pytest.fixture
def lender_agent_headers():
    return TEST_USERS["lender_agent_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]

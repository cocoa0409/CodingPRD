"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def franchisee_owner_headers():
    return TEST_USERS["franchisee_owner_headers"]


@pytest.fixture
def broker_of_record_headers():
    return TEST_USERS["broker_of_record_headers"]


@pytest.fixture
def managing_broker_headers():
    return TEST_USERS["managing_broker_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def trust_accountant_headers():
    return TEST_USERS["trust_accountant_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]

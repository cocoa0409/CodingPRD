"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def second_compliance_officer_headers():
    return TEST_USERS["second_compliance_officer_headers"]


@pytest.fixture
def network_auditor_headers():
    return TEST_USERS["network_auditor_headers"]


@pytest.fixture
def state_regulator_headers():
    return TEST_USERS["state_regulator_headers"]


@pytest.fixture
def merchant_operator_headers():
    return TEST_USERS["merchant_operator_headers"]


@pytest.fixture
def terminal_agent_headers():
    return TEST_USERS["terminal_agent_headers"]

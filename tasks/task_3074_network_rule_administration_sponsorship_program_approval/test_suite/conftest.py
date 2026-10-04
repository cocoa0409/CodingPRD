"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def network_operator_headers():
    return TEST_USERS["network_operator_headers"]


@pytest.fixture
def sponsorship_manager_headers():
    return TEST_USERS["sponsorship_manager_headers"]


@pytest.fixture
def rules_admin_headers():
    return TEST_USERS["rules_admin_headers"]


@pytest.fixture
def rules_admin_2_headers():
    return TEST_USERS["rules_admin_2_headers"]


@pytest.fixture
def rules_admin_3_headers():
    return TEST_USERS["rules_admin_3_headers"]


@pytest.fixture
def dispute_analyst_headers():
    return TEST_USERS["dispute_analyst_headers"]


@pytest.fixture
def pricing_analyst_headers():
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def fraud_analyst_headers():
    return TEST_USERS["fraud_analyst_headers"]


@pytest.fixture
def fraud_analyst_2_headers():
    return TEST_USERS["fraud_analyst_2_headers"]


@pytest.fixture
def settlement_operator_headers():
    return TEST_USERS["settlement_operator_headers"]


@pytest.fixture
def certification_engineer_headers():
    return TEST_USERS["certification_engineer_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]

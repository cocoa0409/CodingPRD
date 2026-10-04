"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def account_headers():
    return TEST_USERS["account_headers"]


@pytest.fixture
def advisor_headers():
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def psap_operator_headers():
    return TEST_USERS["psap_operator_headers"]


@pytest.fixture
def law_enforcement_headers():
    return TEST_USERS["law_enforcement_headers"]


@pytest.fixture
def emergency_operator_headers():
    return TEST_USERS["emergency_operator_headers"]


@pytest.fixture
def dealer_service_headers():
    return TEST_USERS["dealer_service_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def system_ingestion_headers():
    return TEST_USERS["system_ingestion_headers"]

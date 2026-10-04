"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["compliance_analyst_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def settlement_headers():
    return TEST_USERS["settlement_operator_headers"]


@pytest.fixture
def bank_sponsor_headers():
    return TEST_USERS["bank_sponsor_headers"]


@pytest.fixture
def program_manager_headers():
    return TEST_USERS["program_manager_headers"]


@pytest.fixture
def retailer_clerk_headers():
    return TEST_USERS["retailer_clerk_headers"]
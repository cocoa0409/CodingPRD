"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def servicer_agent_headers():
    return TEST_USERS["servicer_agent_headers"]


@pytest.fixture
def merchant_owner_headers():
    return TEST_USERS["merchant_owner_headers"]


@pytest.fixture
def guarantor_principal_headers():
    return TEST_USERS["guarantor_principal_headers"]


@pytest.fixture
def bank_officer_headers():
    return TEST_USERS["bank_officer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]

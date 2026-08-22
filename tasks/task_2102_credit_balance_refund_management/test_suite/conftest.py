"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["refund_approver_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["disbursement_officer_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def liaison_headers():
    return TEST_USERS["payer_liaison_headers"]

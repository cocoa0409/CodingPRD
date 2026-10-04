"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def group_admin_headers():
    return TEST_USERS["group_admin_headers"]


@pytest.fixture
def payer_officer_headers():
    return TEST_USERS["payer_officer_headers"]


@pytest.fixture
def credentialing_coordinator_headers():
    return TEST_USERS["credentialing_coordinator_headers"]


@pytest.fixture
def distribution_accountant_headers():
    return TEST_USERS["distribution_accountant_headers"]


@pytest.fixture
def group_financial_controller_headers():
    return TEST_USERS["group_financial_controller_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]

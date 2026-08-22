"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def operator_headers():
    """TransferAgentOperator — shareholder services desk."""
    return TEST_USERS["operator_headers"]


@pytest.fixture
def accountant_headers():
    """FundAccountant — fund accounting group."""
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def compliance_headers():
    """ComplianceOfficer — compliance and blue-sky desk."""
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def dealer_headers():
    """DealerOperations — selling dealer back office."""
    return TEST_USERS["dealer_headers"]


@pytest.fixture
def account_holder_headers():
    """AccountHolder fallback for calls that are not ownership-gated."""
    return TEST_USERS["account_holder_headers"]

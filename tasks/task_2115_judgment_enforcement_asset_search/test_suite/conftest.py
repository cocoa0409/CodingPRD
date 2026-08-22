"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def asset_investigator_headers():
    return TEST_USERS["asset_investigator_headers"]


@pytest.fixture
def enforcement_officer_headers():
    return TEST_USERS["enforcement_officer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def creditor_headers():
    """Shared constant — only for calls that do not exercise creditor ownership."""
    return TEST_USERS["creditor_headers"]


@pytest.fixture
def debtor_headers():
    """Shared constant — only for calls that do not exercise debtor ownership."""
    return TEST_USERS["debtor_headers"]

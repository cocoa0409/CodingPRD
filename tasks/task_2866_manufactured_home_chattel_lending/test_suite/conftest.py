"""Pytest fixtures exposing the shared test infrastructure.

The runner owns the server lifecycle and injects API_BASE_URL, so these
fixtures only hand tests a client and the pre-built role headers.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointed at the server under test."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def credit_analyst_headers():
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def closing_agent_headers():
    return TEST_USERS["closing_agent_headers"]


@pytest.fixture
def servicer_headers():
    return TEST_USERS["servicer_headers"]


@pytest.fixture
def recovery_manager_headers():
    return TEST_USERS["recovery_manager_headers"]


@pytest.fixture
def community_operator_headers():
    return TEST_USERS["community_operator_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]

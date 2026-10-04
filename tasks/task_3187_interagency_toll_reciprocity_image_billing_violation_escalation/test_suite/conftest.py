"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def settlement_officer_headers():
    return TEST_USERS["settlement_officer_headers"]


@pytest.fixture
def agency_ops_headers():
    return TEST_USERS["agency_ops_headers"]


@pytest.fixture
def account_holder_headers():
    return TEST_USERS["account_holder_headers"]


@pytest.fixture
def violations_officer_headers():
    return TEST_USERS["violations_officer_headers"]


@pytest.fixture
def plate_lookup_agent_headers():
    return TEST_USERS["plate_lookup_agent_headers"]

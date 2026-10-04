"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle is managed externally; tests assume the API is already
reachable and that the database is empty at the start of each test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def risk_officer_creator_headers():
    return TEST_USERS["risk_officer_creator_headers"]


@pytest.fixture
def risk_officer_validator_headers():
    return TEST_USERS["risk_officer_validator_headers"]


@pytest.fixture
def risk_officer_attester_headers():
    return TEST_USERS["risk_officer_attester_headers"]


@pytest.fixture
def partner_admin_headers():
    return TEST_USERS["partner_admin_headers"]


@pytest.fixture
def partner_admin_two_headers():
    return TEST_USERS["partner_admin_two_headers"]


@pytest.fixture
def verification_officer_headers():
    return TEST_USERS["verification_officer_headers"]


@pytest.fixture
def verification_officer_two_headers():
    return TEST_USERS["verification_officer_two_headers"]


@pytest.fixture
def servicing_agent_headers():
    return TEST_USERS["servicing_agent_headers"]


@pytest.fixture
def collections_agent_headers():
    return TEST_USERS["collections_agent_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]

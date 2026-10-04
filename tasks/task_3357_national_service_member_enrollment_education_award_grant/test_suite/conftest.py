"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the harness; tests assume the API is already
reachable at API_BASE_URL and starts from an empty database per test.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is managed externally."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def trust_admin_headers():
    return TEST_USERS["trust_admin_headers"]


@pytest.fixture
def grantee_staff_headers():
    return TEST_USERS["grantee_staff_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]

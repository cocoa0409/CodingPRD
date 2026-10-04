"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def advisor_ops_headers():
    return TEST_USERS["advisor_ops_headers"]


@pytest.fixture
def support_analyst_headers():
    return TEST_USERS["support_analyst_headers"]


@pytest.fixture
def custody_officer_headers():
    return TEST_USERS["custody_officer_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def committee_chair_headers():
    return TEST_USERS["committee_chair_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]
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
def billing_contact_headers():
    return TEST_USERS["billing_contact_headers"]


@pytest.fixture
def trust_analyst_headers():
    return TEST_USERS["trust_analyst_headers"]


@pytest.fixture
def trust_lead_headers():
    return TEST_USERS["trust_lead_headers"]


@pytest.fixture
def organization_admin_headers():
    return TEST_USERS["organization_admin_headers"]

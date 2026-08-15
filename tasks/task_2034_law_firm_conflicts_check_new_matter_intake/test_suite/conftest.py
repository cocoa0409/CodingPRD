"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def firm_admin_headers():
    return TEST_USERS["firm_admin_headers"]


@pytest.fixture
def intake_specialist_headers():
    return TEST_USERS["intake_specialist_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]


@pytest.fixture
def responsible_attorney_headers():
    return TEST_USERS["responsible_attorney_headers"]


@pytest.fixture
def conflicts_partner_headers():
    return TEST_USERS["conflicts_partner_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]

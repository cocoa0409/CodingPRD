"""Pytest fixtures exposing the antitrust compliance test helpers."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def compliance_admin_headers():
    return TEST_USERS["compliance_admin_headers"]


@pytest.fixture
def antitrust_counsel_headers():
    return TEST_USERS["antitrust_counsel_headers"]


@pytest.fixture
def business_lead_headers():
    return TEST_USERS["business_lead_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]

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
def regional_manager_headers():
    return TEST_USERS["regional_manager_headers"]


@pytest.fixture
def field_consultant_headers():
    return TEST_USERS["field_consultant_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def survey_vendor_headers():
    return TEST_USERS["survey_vendor_headers"]


@pytest.fixture
def dealer_principal_headers():
    return TEST_USERS["dealer_principal_headers"]


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]

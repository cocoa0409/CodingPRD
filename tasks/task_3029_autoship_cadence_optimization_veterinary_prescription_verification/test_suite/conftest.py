"""Pytest fixture bridge exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ANONYMOUS_HEADERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's responsibility."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def clinic_contact_headers():
    return TEST_USERS["clinic_contact_headers"]


@pytest.fixture
def pharmacy_technician_headers():
    return TEST_USERS["pharmacy_technician_headers"]


@pytest.fixture
def pharmacy_manager_headers():
    return TEST_USERS["pharmacy_manager_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
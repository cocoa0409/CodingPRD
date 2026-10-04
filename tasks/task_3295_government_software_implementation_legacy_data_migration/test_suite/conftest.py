"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin"]


@pytest.fixture
def procurement_headers():
    return TEST_USERS["procurement_officer"]


@pytest.fixture
def impl_headers():
    return TEST_USERS["implementation_manager"]


@pytest.fixture
def agency_pm_headers():
    return TEST_USERS["agency_pm"]


@pytest.fixture
def vendor_pm_headers():
    return TEST_USERS["vendor_pm"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_officer"]


@pytest.fixture
def ba_headers():
    return TEST_USERS["business_analyst"]


@pytest.fixture
def dml_headers():
    return TEST_USERS["data_migration_lead"]


@pytest.fixture
def iface_headers():
    return TEST_USERS["interface_engineer"]


@pytest.fixture
def support_headers():
    return TEST_USERS["support_manager"]

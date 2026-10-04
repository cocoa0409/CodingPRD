"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def data_acquisition_manager_headers():
    return TEST_USERS["data_acquisition_manager_headers"]


@pytest.fixture
def privacy_officer_headers():
    return TEST_USERS["privacy_officer_headers"]


@pytest.fixture
def supplier_operator_headers():
    return TEST_USERS["supplier_operator_headers"]


@pytest.fixture
def manufacturer_client_headers():
    return TEST_USERS["manufacturer_client_headers"]

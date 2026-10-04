"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def pro_registrar_headers():
    return TEST_USERS["pro_registrar_headers"]


@pytest.fixture
def pro_licensing_admin_headers():
    return TEST_USERS["pro_licensing_admin_headers"]


@pytest.fixture
def rate_court_officer_headers():
    return TEST_USERS["rate_court_officer_headers"]


@pytest.fixture
def royalty_distributor_headers():
    return TEST_USERS["royalty_distributor_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_officer_2_headers():
    return TEST_USERS["finance_officer_2_headers"]


@pytest.fixture
def pro_system_admin_headers():
    return TEST_USERS["pro_system_admin_headers"]

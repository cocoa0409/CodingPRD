"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, default_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return default_client


@pytest.fixture
def state_admin_headers():
    return TEST_USERS["state_admin_headers"]


@pytest.fixture
def csr_headers():
    return TEST_USERS["csr_headers"]


@pytest.fixture
def csr_alt_headers():
    return TEST_USERS["csr_alt_headers"]


@pytest.fixture
def cardholder_headers():
    return TEST_USERS["cardholder_headers"]


@pytest.fixture
def retailer_system_headers():
    return TEST_USERS["retailer_system_headers"]

"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def workshop_associate_headers():
    return TEST_USERS["workshop_associate_headers"]


@pytest.fixture
def party_host_headers():
    return TEST_USERS["party_host_headers"]


@pytest.fixture
def store_manager_headers():
    return TEST_USERS["store_manager_headers"]

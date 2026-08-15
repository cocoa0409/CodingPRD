"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def analyst2_headers():
    return TEST_USERS["analyst2_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def accountant_headers():
    return TEST_USERS["accountant_headers"]


@pytest.fixture
def recovery_headers():
    return TEST_USERS["recovery_headers"]


@pytest.fixture
def gateway_headers():
    return TEST_USERS["gateway_headers"]


@pytest.fixture
def cardholder_headers():
    return TEST_USERS["cardholder_headers"]

"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def commercial_headers():
    return TEST_USERS["commercial_headers"]


@pytest.fixture
def gas_headers():
    return TEST_USERS["gas_headers"]


@pytest.fixture
def marine_headers():
    return TEST_USERS["marine_headers"]


@pytest.fixture
def customer_rep_headers():
    return TEST_USERS["customer_rep_headers"]

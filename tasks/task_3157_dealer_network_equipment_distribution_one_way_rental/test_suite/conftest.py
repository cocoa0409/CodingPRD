"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin"]


@pytest.fixture
def pricing_headers():
    return TEST_USERS["pricing"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance"]


@pytest.fixture
def driver_headers():
    return TEST_USERS["driver_1"]

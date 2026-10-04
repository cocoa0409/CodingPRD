"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def care():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def analyst():
    return TEST_USERS["credit_analyst_headers"]


@pytest.fixture
def inspector():
    return TEST_USERS["trade_in_inspector_headers"]


@pytest.fixture
def customer():
    return TEST_USERS["customer_headers"]
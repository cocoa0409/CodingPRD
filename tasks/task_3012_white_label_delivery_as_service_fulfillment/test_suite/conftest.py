"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def merchant_headers():
    return TEST_USERS["merchant_headers"]


@pytest.fixture
def courier_headers():
    return TEST_USERS["courier_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def support_agent_headers():
    return TEST_USERS["support_agent_headers"]

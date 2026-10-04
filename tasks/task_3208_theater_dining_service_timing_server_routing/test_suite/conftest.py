"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def lead_headers():
    return TEST_USERS["kitchen_lead_headers"]


@pytest.fixture
def programmer_headers():
    return TEST_USERS["programming_coordinator_headers"]


@pytest.fixture
def producer_headers():
    return TEST_USERS["pre_show_producer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def server_headers():
    return TEST_USERS["server_headers"]
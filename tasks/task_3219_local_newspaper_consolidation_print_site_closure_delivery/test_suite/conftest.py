"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; tests only consume the
API client and role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def print_ops_headers():
    return TEST_USERS["print_ops_headers"]


@pytest.fixture
def delivery_manager_headers():
    return TEST_USERS["delivery_manager_headers"]


@pytest.fixture
def newsroom_manager_headers():
    return TEST_USERS["newsroom_manager_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]
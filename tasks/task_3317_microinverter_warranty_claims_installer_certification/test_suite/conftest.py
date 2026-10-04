"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def installer_headers():
    return TEST_USERS["installer_headers"]


@pytest.fixture
def monitoring_service_headers():
    return TEST_USERS["monitoring_service_headers"]


@pytest.fixture
def homeowner_headers():
    return TEST_USERS["homeowner_headers"]
"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def compliance_analyst_headers():
    return TEST_USERS["compliance_analyst_headers"]


@pytest.fixture
def data_ops_headers():
    return TEST_USERS["data_ops_headers"]

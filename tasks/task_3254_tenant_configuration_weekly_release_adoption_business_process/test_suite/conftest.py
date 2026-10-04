"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_operator_headers():
    return TEST_USERS["platform_operator_headers"]


@pytest.fixture
def integration_developer_headers():
    return TEST_USERS["integration_developer_headers"]


@pytest.fixture
def tenant_admin_headers():
    return TEST_USERS["tenant_admin_headers"]


@pytest.fixture
def implementation_partner_headers():
    return TEST_USERS["implementation_partner_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]

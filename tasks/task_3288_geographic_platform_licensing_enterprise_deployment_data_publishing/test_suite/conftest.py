"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def license_admin_headers():
    return TEST_USERS["license_admin_headers"]


@pytest.fixture
def deployment_admin_headers():
    return TEST_USERS["deployment_admin_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def content_moderator_headers():
    return TEST_USERS["content_moderator_headers"]


@pytest.fixture
def named_user_headers():
    return TEST_USERS["named_user_headers"]

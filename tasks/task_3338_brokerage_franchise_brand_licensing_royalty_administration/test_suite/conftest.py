"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def franchisor_ops_headers():
    return TEST_USERS["franchisor_ops_headers"]


@pytest.fixture
def franchisee_admin_headers():
    return TEST_USERS["franchisee_admin_headers"]


@pytest.fixture
def brand_auditor_headers():
    return TEST_USERS["brand_auditor_headers"]

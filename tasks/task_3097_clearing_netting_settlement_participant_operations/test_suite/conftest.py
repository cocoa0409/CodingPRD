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
def risk_headers():
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def member_headers():
    """Fallback ClearingMember headers for calls that are not ownership-gated."""
    return TEST_USERS["clearing_member_headers"]
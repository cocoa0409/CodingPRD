"""Pytest fixtures exposing the test_helpers infrastructure.

The server lifecycle is owned by prd-bench-local-runner: it restarts the API
before every individual test, so each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointed at API_BASE_URL."""
    return api_client


@pytest.fixture
def admin_headers():
    """NetworkAdmin operator headers."""
    return TEST_USERS["admin_headers"]


@pytest.fixture
def auditor_headers():
    """NetworkAuditor operator headers."""
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def member_headers():
    """Shared MemberFoodBank headers — only for calls that are not ownership-gated."""
    return TEST_USERS["member_headers"]

"""Pytest fixtures exposing test_helpers infrastructure.

The runner supplies API_BASE_URL and PYTHONPATH; server lifecycle is the runner's
responsibility, so these fixtures only wire up the client and role headers.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]


@pytest.fixture
def partner_admin_headers():
    return TEST_USERS["partner_admin_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
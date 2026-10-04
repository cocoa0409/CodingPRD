"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def rate_admin_headers():
    return TEST_USERS["rate_filing_admin_headers"]


@pytest.fixture
def adjuster_1_headers():
    return TEST_USERS["adjuster_1_headers"]


@pytest.fixture
def adjuster_2_headers():
    return TEST_USERS["adjuster_2_headers"]

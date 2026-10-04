"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def bureau_admin_headers():
    return TEST_USERS["bureau_admin_headers"]


@pytest.fixture
def bureau_analyst_headers():
    return TEST_USERS["bureau_analyst_headers"]


@pytest.fixture
def pool_administrator_headers():
    return TEST_USERS["pool_administrator_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]

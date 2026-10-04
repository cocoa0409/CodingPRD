"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def regional_director_headers():
    return TEST_USERS["regional_director_headers"]


@pytest.fixture
def market_center_admin_headers():
    return TEST_USERS["market_center_admin_headers"]


@pytest.fixture
def alc_chair_headers():
    return TEST_USERS["alc_chair_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]

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
def yard_operator_headers():
    return TEST_USERS["yard_operator_headers"]


@pytest.fixture
def auctioneer_headers():
    return TEST_USERS["auctioneer_headers"]


@pytest.fixture
def title_clerk_headers():
    return TEST_USERS["title_clerk_headers"]


@pytest.fixture
def seller_agent_headers():
    return TEST_USERS["seller_agent_headers"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]

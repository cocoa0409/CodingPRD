"""Pytest fixtures exposing the generated test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, api_client, ApiClient


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's guarantee."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]


@pytest.fixture
def fulfillment_headers():
    return TEST_USERS["fulfillment_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def subscriber_headers():
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def partner_headers():
    return TEST_USERS["partner_headers"]
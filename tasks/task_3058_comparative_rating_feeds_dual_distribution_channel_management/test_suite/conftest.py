"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def carrier_admin_headers():
    return TEST_USERS["carrier_admin_headers"]


@pytest.fixture
def rating_manager_headers():
    return TEST_USERS["rating_manager_headers"]


@pytest.fixture
def underwriting_reviewer_headers():
    return TEST_USERS["underwriting_reviewer_headers"]


@pytest.fixture
def underwriting_reviewer_2_headers():
    return TEST_USERS["underwriting_reviewer_2_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def consumer_headers():
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def agent_headers():
    return TEST_USERS["agent_headers"]

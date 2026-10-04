"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def acceptance_agent_headers():
    return TEST_USERS["acceptance_agent_headers"]


@pytest.fixture
def sortation_agent_headers():
    return TEST_USERS["sortation_agent_headers"]


@pytest.fixture
def screener_headers():
    return TEST_USERS["screener_headers"]


@pytest.fixture
def load_agent_headers():
    return TEST_USERS["load_agent_headers"]


@pytest.fixture
def transfer_agent_headers():
    return TEST_USERS["transfer_agent_headers"]


@pytest.fixture
def baggage_service_agent_headers():
    return TEST_USERS["baggage_service_agent_headers"]


@pytest.fixture
def passenger_headers():
    return TEST_USERS["passenger_headers"]
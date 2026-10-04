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
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def ingestion_agent_headers():
    return TEST_USERS["ingestion_agent_headers"]


@pytest.fixture
def team_lead_headers():
    return TEST_USERS["team_lead_headers"]


@pytest.fixture
def finance_reader_headers():
    return TEST_USERS["finance_reader_headers"]

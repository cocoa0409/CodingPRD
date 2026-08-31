"""Pytest fixtures exposing the generated test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def volunteer_headers():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def expert_headers():
    return TEST_USERS["expert_headers"]


@pytest.fixture
def research_partner_headers():
    return TEST_USERS["research_partner_headers"]

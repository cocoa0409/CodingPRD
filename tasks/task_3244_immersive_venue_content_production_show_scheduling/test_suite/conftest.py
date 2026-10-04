"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def production_director_headers():
    return TEST_USERS["production_director_headers"]


@pytest.fixture
def content_producer_headers():
    return TEST_USERS["content_producer_headers"]


@pytest.fixture
def venue_scheduler_headers():
    return TEST_USERS["venue_scheduler_headers"]


@pytest.fixture
def venue_ops_engineer_headers():
    return TEST_USERS["venue_ops_engineer_headers"]


@pytest.fixture
def sponsorship_manager_headers():
    return TEST_USERS["sponsorship_manager_headers"]


@pytest.fixture
def box_office_agent_headers():
    return TEST_USERS["box_office_agent_headers"]


@pytest.fixture
def guest_headers():
    return TEST_USERS["guest_headers"]

"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def complex_director_headers():
    return TEST_USERS["complex_director_headers"]


@pytest.fixture
def community_liaison_headers():
    return TEST_USERS["community_liaison_headers"]


@pytest.fixture
def field_coordinator_headers():
    return TEST_USERS["field_coordinator_headers"]


@pytest.fixture
def pitching_coordinator_headers():
    return TEST_USERS["pitching_coordinator_headers"]


@pytest.fixture
def travel_coordinator_headers():
    return TEST_USERS["travel_coordinator_headers"]


@pytest.fixture
def team_physician_headers():
    return TEST_USERS["team_physician_headers"]


@pytest.fixture
def roster_manager_headers():
    return TEST_USERS["roster_manager_headers"]


@pytest.fixture
def minor_league_coordinator_headers():
    return TEST_USERS["minor_league_coordinator_headers"]


@pytest.fixture
def analytics_headers():
    return TEST_USERS["analytics_headers"]


@pytest.fixture
def player_headers():
    return TEST_USERS["player_headers"]
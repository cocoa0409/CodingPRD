"""Pytest fixtures exposing test_helpers infrastructure.

The server lifecycle (start/stop/restart per test) is owned by the runner;
this module only wires the generated helpers into pytest fixtures.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client pointing at API_BASE_URL."""
    return api_client


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def league_admin_headers():
    return TEST_USERS["league_admin_headers"]


@pytest.fixture
def tournament_director_headers():
    return TEST_USERS["tournament_director_headers"]


@pytest.fixture
def official_scorer_headers():
    return TEST_USERS["official_scorer_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]

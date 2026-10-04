"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def np_headers():
    return TEST_USERS["network_planner_headers"]


@pytest.fixture
def cd_headers():
    return TEST_USERS["crew_dispatcher_headers"]


@pytest.fixture
def pp_headers():
    return TEST_USERS["power_planner_headers"]


@pytest.fixture
def ts_headers():
    return TEST_USERS["terminal_superintendent_headers"]


@pytest.fixture
def sm_headers():
    return TEST_USERS["service_manager_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]

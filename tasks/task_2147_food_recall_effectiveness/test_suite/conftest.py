"""Pytest fixtures exposing the shared test infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def firm_officer_headers():
    return TEST_USERS["firm_officer_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def second_coordinator_headers():
    return TEST_USERS["second_coordinator_headers"]


@pytest.fixture
def panel_headers():
    return TEST_USERS["panel_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]

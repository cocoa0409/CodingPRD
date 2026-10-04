"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def council_admin_headers():
    return TEST_USERS["council_admin_headers"]


@pytest.fixture
def troop_leader_headers():
    return TEST_USERS["troop_leader_headers"]

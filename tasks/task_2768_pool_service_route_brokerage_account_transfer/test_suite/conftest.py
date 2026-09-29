"""Pytest fixtures exposing the shared API client and the role headers.

The runner relaunches the server before every individual test, so each test
starts against an empty database and builds its own state through the endpoints
of PRD §4.
"""
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
def broker_headers():
    return TEST_USERS["broker_headers"]


@pytest.fixture
def escrow_agent_headers():
    return TEST_USERS["escrow_agent_headers"]

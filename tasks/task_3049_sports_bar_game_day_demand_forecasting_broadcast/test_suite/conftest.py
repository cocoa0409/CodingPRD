"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import (
    HOST_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    SCHEDULER_HEADERS,
    SERVER_HEADERS,
    TEST_USERS,
    VENUE_MANAGER_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return PLATFORM_ADMIN_HEADERS


@pytest.fixture
def venue_manager_headers():
    return VENUE_MANAGER_HEADERS


@pytest.fixture
def host_headers():
    return HOST_HEADERS


@pytest.fixture
def server_headers():
    return SERVER_HEADERS


@pytest.fixture
def scheduler_headers():
    return SCHEDULER_HEADERS

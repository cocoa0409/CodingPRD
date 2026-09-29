"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared API client; the runner injects API_BASE_URL."""
    return api_client


@pytest.fixture(scope="session")
def users() -> dict:
    """Pre-built role headers keyed by role name."""
    return TEST_USERS

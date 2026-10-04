"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def moderator_headers():
    return TEST_USERS["moderator"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin"]

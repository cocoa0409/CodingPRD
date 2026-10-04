"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def scale_operator_headers():
    return TEST_USERS["scale_operator_headers"]


@pytest.fixture
def deli_manager_headers():
    return TEST_USERS["deli_manager_headers"]


@pytest.fixture
def deli_clerk_headers():
    return TEST_USERS["deli_clerk_headers"]


@pytest.fixture
def bakery_coordinator_headers():
    return TEST_USERS["bakery_coordinator_headers"]
"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return dict(TEST_USERS["admin_headers"])


@pytest.fixture
def manager_headers():
    return dict(TEST_USERS["manager_headers"])


@pytest.fixture
def manager_2_headers():
    return dict(TEST_USERS["manager_2_headers"])


@pytest.fixture
def clerk_headers():
    return dict(TEST_USERS["clerk_headers"])


@pytest.fixture
def clerk_2_headers():
    return dict(TEST_USERS["clerk_2_headers"])


@pytest.fixture
def auditor_headers():
    return dict(TEST_USERS["auditor_headers"])

"""Pytest fixtures exposing the grazing test_helpers infrastructure."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's job."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def grazier_headers():
    return TEST_USERS["grazier_headers"]


@pytest.fixture
def cattle_owner_headers():
    return TEST_USERS["cattle_owner_headers"]


@pytest.fixture
def range_consultant_headers():
    return TEST_USERS["range_consultant_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
